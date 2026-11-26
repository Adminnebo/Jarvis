package com.neboai.jarvis;

import android.os.Bundle;

import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    @Override
    public void onCreate(Bundle savedInstanceState) {
        registerPlugin(GrabadoraPlugin.class);   // grabar reuniones presenciales con la pantalla apagada
        super.onCreate(savedInstanceState);
    }
}
