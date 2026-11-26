package com.neboai.jarvis;

import android.Manifest;
import android.content.Intent;
import android.os.Build;

import androidx.core.content.ContextCompat;

import com.getcapacitor.JSObject;
import com.getcapacitor.PermissionState;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;
import com.getcapacitor.annotation.Permission;
import com.getcapacitor.annotation.PermissionCallback;

/** Puente de web/apps/grabadora.js al servicio de grabación (ver GrabadoraServicio). */
@CapacitorPlugin(name = "GrabadoraPresencial", permissions = {
        @Permission(alias = "microfono", strings = { Manifest.permission.RECORD_AUDIO }),
        @Permission(alias = "avisos", strings = { Manifest.permission.POST_NOTIFICATIONS }) })
public class GrabadoraPlugin extends Plugin {

    @Override
    public void load() {
        // Lo que quedó sin subir de una vez anterior (sin red, o la app se cerró).
        if (!GrabadoraServicio.grabando && GrabadoraServicio.pendientes(getContext().getFilesDir()) > 0) {
            ContextCompat.startForegroundService(getContext(),
                    new Intent(getContext(), GrabadoraServicio.class).setAction(GrabadoraServicio.SUBIR));
        }
    }

    @PluginMethod
    public void iniciar(PluginCall call) {
        boolean faltaAvisos = Build.VERSION.SDK_INT >= 33 && getPermissionState("avisos") != PermissionState.GRANTED;
        if (getPermissionState("microfono") != PermissionState.GRANTED || faltaAvisos) {
            requestPermissionForAliases(new String[] { "microfono", "avisos" }, call, "trasPermiso");
            return;
        }
        arrancar(call);
    }

    @PermissionCallback
    private void trasPermiso(PluginCall call) {
        if (getPermissionState("microfono") == PermissionState.GRANTED) arrancar(call);
        else call.reject("sin_permiso");
    }

    private void arrancar(PluginCall call) {
        Intent i = new Intent(getContext(), GrabadoraServicio.class).setAction(GrabadoraServicio.INICIAR)
                .putExtra("reunion", call.getString("reunionId"))
                .putExtra("token", call.getString("token"))
                .putExtra("titulo", call.getString("titulo", ""))
                .putExtra("base", call.getString("base"))
                .putExtra("pedazoS", call.getInt("pedazoS", 300))
                .putExtra("maxS", call.getInt("maxS", 14400));
        ContextCompat.startForegroundService(getContext(), i);
        call.resolve();
    }

    @PluginMethod
    public void terminar(PluginCall call) {
        if (GrabadoraServicio.grabando) {
            getContext().startService(new Intent(getContext(), GrabadoraServicio.class)
                    .setAction(GrabadoraServicio.TERMINAR));
        }
        call.resolve();
    }

    @PluginMethod
    public void estado(PluginCall call) {
        JSObject o = new JSObject();
        o.put("grabando", GrabadoraServicio.grabando);
        o.put("reunionId", GrabadoraServicio.reunionId);
        o.put("titulo", GrabadoraServicio.titulo);
        o.put("segundos", GrabadoraServicio.grabando ? (System.currentTimeMillis() - GrabadoraServicio.desdeMs) / 1000 : 0);
        o.put("pendientes", GrabadoraServicio.pendientes(getContext().getFilesDir()));
        call.resolve(o);
    }
}
