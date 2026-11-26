package com.neboai.jarvis;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.media.MediaRecorder;
import android.os.Build;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.os.PowerManager;

import androidx.core.app.NotificationCompat;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.Locale;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * Graba una reunión presencial en pedazos OGG/Opus y los sube a Jarvis con el token de
 * la reunión, aunque la pantalla esté apagada o la app cerrada.
 *
 * Cola en files/cola/<reunion>/: 00001_0.ogg (n_inicio en segundos), "token", "base" y,
 * cuando terminó, "fin" (el motivo). Un pedazo se borra al recibir 200 o 409; con 401 o
 * 404 se descarta la reunión entera. Cuando no queda nada, avisa "terminado" y se apaga.
 * Ver docs/superpowers/specs/2026-11-26-reuniones-presenciales-design.md.
 */
public class GrabadoraServicio extends Service {
    static final String INICIAR = "iniciar", TERMINAR = "terminar", SUBIR = "subir";
    static final String CANAL = "grabacion";
    static final int AVISO = 7;

    static volatile boolean grabando = false;
    static volatile String reunionId = null, titulo = "";
    static volatile long desdeMs = 0;

    private final Handler h = new Handler(Looper.getMainLooper());
    private final ExecutorService subidas = Executors.newSingleThreadExecutor();
    private MediaRecorder rec;
    private File actual;
    private int n = 0, pedazoS = 300, maxS = 14400;
    private PowerManager.WakeLock despierto;
    private boolean reintentoPendiente = false;

    @Override
    public IBinder onBind(Intent i) { return null; }

    @Override
    public int onStartCommand(Intent i, int flags, int startId) {
        String accion = i != null && i.getAction() != null ? i.getAction() : SUBIR;
        if (INICIAR.equals(accion) && !grabando) {
            reunionId = i.getStringExtra("reunion");
            titulo = i.getStringExtra("titulo");
            pedazoS = Math.max(5, i.getIntExtra("pedazoS", 300));
            maxS = i.getIntExtra("maxS", 14400);
            File dir = cola(reunionId);
            escribir(new File(dir, "token"), i.getStringExtra("token"));
            escribir(new File(dir, "base"), i.getStringExtra("base"));
            primerPlano("Empezando…");
            despierto = ((PowerManager) getSystemService(POWER_SERVICE))
                    .newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "jarvis:grabacion");
            despierto.acquire(maxS * 1000L + 60_000L);
            grabando = true;
            desdeMs = System.currentTimeMillis();
            n = 0;
            nuevoPedazo();
            h.postDelayed(this::rotar, pedazoS * 1000L);
            reloj();   // ya con grabando = true: la notificación trae «Terminar» desde el inicio
        } else if (TERMINAR.equals(accion)) {
            terminar("usuario");
        } else {
            if (!grabando) primerPlano("Subiendo grabación…");
            subir();
        }
        return START_NOT_STICKY;
    }

    private void primerPlano(String texto) {
        NotificationManager nm = getSystemService(NotificationManager.class);
        nm.createNotificationChannel(new NotificationChannel(CANAL, "Grabación de reuniones",
                NotificationManager.IMPORTANCE_LOW));
        Intent abrir = getPackageManager().getLaunchIntentForPackage(getPackageName());
        PendingIntent alTocar = PendingIntent.getActivity(this, 0, abrir, PendingIntent.FLAG_IMMUTABLE);
        PendingIntent fin = PendingIntent.getService(this, 1,
                new Intent(this, GrabadoraServicio.class).setAction(TERMINAR), PendingIntent.FLAG_IMMUTABLE);
        NotificationCompat.Builder b = new NotificationCompat.Builder(this, CANAL)
                .setSmallIcon(android.R.drawable.ic_btn_speak_now)
                .setContentTitle(titulo == null || titulo.isEmpty() ? "Jarvis está grabando" : titulo)
                .setContentText(texto)
                .setOngoing(true)
                .setOnlyAlertOnce(true)
                .setContentIntent(alTocar);
        if (grabando) b.addAction(0, "Terminar", fin);
        Notification aviso = b.build();
        startForeground(AVISO, aviso, ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE);
    }

    private void reloj() {
        if (!grabando) return;
        long s = (System.currentTimeMillis() - desdeMs) / 1000;
        primerPlano(String.format(Locale.ROOT, "Grabando · %d:%02d", s / 60, s % 60));
        h.postDelayed(this::reloj, 30_000L);
    }

    private void nuevoPedazo() {
        n++;
        long inicioS = (System.currentTimeMillis() - desdeMs) / 1000;
        actual = new File(cola(reunionId), String.format(Locale.ROOT, "%05d_%d.grabando", n, inicioS));
        rec = Build.VERSION.SDK_INT >= 31 ? new MediaRecorder(this) : new MediaRecorder();
        rec.setAudioSource(MediaRecorder.AudioSource.MIC);
        rec.setOutputFormat(MediaRecorder.OutputFormat.OGG);
        rec.setAudioEncoder(MediaRecorder.AudioEncoder.OPUS);
        rec.setAudioChannels(1);
        rec.setAudioSamplingRate(16000);
        rec.setAudioEncodingBitRate(24000);
        rec.setOutputFile(actual.getAbsolutePath());
        try {
            rec.prepare();
            rec.start();
        } catch (Exception e) {
            rec.release();
            rec = null;
            terminar("fallo");
        }
    }

    /** Cierra el pedazo que se está grabando y lo deja en la cola como .ogg. */
    private void cerrarPedazo() {
        if (rec == null) return;
        try {
            rec.stop();
        } catch (Exception ignorado) {
            // pedazo demasiado corto: queda vacío y se borra abajo
        }
        rec.release();
        rec = null;
        if (actual.length() > 0) actual.renameTo(new File(actual.getParentFile(), actual.getName().replace(".grabando", ".ogg")));
        else actual.delete();
    }

    private void rotar() {
        if (!grabando) return;
        if ((System.currentTimeMillis() - desdeMs) / 1000 >= maxS) {
            terminar("maximo");
            return;
        }
        cerrarPedazo();
        nuevoPedazo();
        subir();
        h.postDelayed(this::rotar, pedazoS * 1000L);
    }

    private void terminar(String motivo) {
        if (grabando) {
            grabando = false;
            h.removeCallbacksAndMessages(null);
            cerrarPedazo();
            escribir(new File(cola(reunionId), "fin"), motivo);
            if (despierto != null && despierto.isHeld()) despierto.release();
        }
        primerPlano("Subiendo grabación…");
        subir();
    }

    private File cola(String reunion) {
        File d = new File(new File(getFilesDir(), "cola"), reunion);
        d.mkdirs();
        return d;
    }

    // ------------------------------------------------------------ subir

    private void subir() {
        subidas.execute(() -> {
            boolean pendiente = false;
            File[] reuniones = new File(getFilesDir(), "cola").listFiles();
            if (reuniones != null) for (File dir : reuniones) pendiente |= subirReunion(dir);
            final boolean quedaAlgo = pendiente;
            h.post(() -> {
                if (quedaAlgo) {
                    if (!reintentoPendiente) {   // sin red: se reintenta en 30 s
                        reintentoPendiente = true;
                        h.postDelayed(() -> { reintentoPendiente = false; subir(); }, 30_000L);
                    }
                } else if (!grabando) {
                    stopForeground(STOP_FOREGROUND_REMOVE);
                    stopSelf();
                }
            });
        });
    }

    /** true si quedó algo por subir por falta de red (no si sigue grabando). */
    private boolean subirReunion(File dir) {
        String id = dir.getName();
        String token = leer(new File(dir, "token")), base = leer(new File(dir, "base"));
        if (token == null || base == null) {
            borrar(dir);
            return false;
        }
        File[] pedazos = dir.listFiles((d, nombre) -> nombre.endsWith(".ogg"));
        if (pedazos == null) pedazos = new File[0];
        Arrays.sort(pedazos);
        for (File p : pedazos) {
            String[] partes = p.getName().replace(".ogg", "").split("_");
            int codigo;
            String cuerpo = "";
            try {
                HttpURLConnection c = (HttpURLConnection) new URL(base + "/api/reuniones/" + id + "/audio?n="
                        + Integer.parseInt(partes[0]) + "&inicio_s=" + partes[1]).openConnection();
                c.setRequestMethod("POST");
                c.setDoOutput(true);
                c.setConnectTimeout(20_000);
                c.setReadTimeout(60_000);
                c.setRequestProperty("Authorization", "Bearer " + token);
                c.setRequestProperty("Content-Type", "audio/ogg");
                c.setFixedLengthStreamingMode(p.length());
                try (OutputStream out = c.getOutputStream(); InputStream in = new FileInputStream(p)) {
                    byte[] buf = new byte[16384];
                    for (int k; (k = in.read(buf)) > 0; ) out.write(buf, 0, k);
                }
                codigo = c.getResponseCode();
                if (codigo == 200) cuerpo = leerTodo(c.getInputStream());
                c.disconnect();
            } catch (Exception sinRed) {
                return true;
            }
            if (codigo == 401 || codigo == 404) {
                borrar(dir);
                return false;
            }
            if (codigo != 200 && codigo != 409) return true;
            p.delete();
            if (cuerpo.replace(" ", "").contains("\"parar\":true") && grabando && id.equals(reunionId)) {
                h.post(() -> terminar("sacada"));
            }
        }
        String motivo = leer(new File(dir, "fin"));
        if (motivo == null) return false;   // sigue grabando: lo que falta llega con el próximo pedazo
        try {
            HttpURLConnection c = (HttpURLConnection) new URL(base + "/api/reuniones/" + id + "/eventos").openConnection();
            c.setRequestMethod("POST");
            c.setDoOutput(true);
            c.setConnectTimeout(20_000);
            c.setRequestProperty("Authorization", "Bearer " + token);
            c.setRequestProperty("Content-Type", "application/json");
            try (OutputStream out = c.getOutputStream()) {
                out.write(("{\"tipo\":\"terminado\",\"motivo\":\"" + motivo + "\"}").getBytes(StandardCharsets.UTF_8));
            }
            int codigo = c.getResponseCode();
            c.disconnect();
            if (codigo == 200 || codigo == 401 || codigo == 404) {
                borrar(dir);
                return false;
            }
        } catch (Exception sinRed) {
            // se reintenta
        }
        return true;
    }

    static int pendientes(File filesDir) {
        int total = 0;
        File[] reuniones = new File(filesDir, "cola").listFiles();
        if (reuniones != null) {
            for (File d : reuniones) {
                File[] p = d.listFiles((x, nombre) -> nombre.endsWith(".ogg") || nombre.equals("fin"));
                total += p == null ? 0 : p.length;
            }
        }
        return total;
    }

    private static String leerTodo(InputStream in) throws java.io.IOException {
        ByteArrayOutputStream b = new ByteArrayOutputStream();
        byte[] buf = new byte[4096];
        for (int k; (k = in.read(buf)) > 0; ) b.write(buf, 0, k);
        in.close();
        return b.toString("UTF-8");
    }

    private static void escribir(File f, String texto) {
        try (OutputStream out = new FileOutputStream(f)) {
            out.write((texto == null ? "" : texto).getBytes(StandardCharsets.UTF_8));
        } catch (Exception ignorado) {
            // sin disco: no hay mucho que hacer
        }
    }

    private static String leer(File f) {
        try (InputStream in = new FileInputStream(f)) {
            String s = leerTodo(in).trim();
            return s.isEmpty() ? null : s;
        } catch (Exception e) {
            return null;
        }
    }

    private static void borrar(File dir) {
        File[] todo = dir.listFiles();
        if (todo != null) for (File f : todo) f.delete();
        dir.delete();
    }
}
