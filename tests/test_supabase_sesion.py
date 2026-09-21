import pytest

from backend import supabase_sesion


SERVICE = "service-de-prueba"


@pytest.fixture
def configurado(monkeypatch):
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon-de-prueba")
    monkeypatch.setenv("SUPABASE_PROJECT_REF", "abcdefghijklmnopqrst")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", SERVICE)


def test_sin_variables_el_puente_esta_apagado():
    assert supabase_sesion.configurado() is False


def test_con_las_tres_variables_esta_encendido(configurado):
    assert supabase_sesion.configurado() is True


def test_falta_la_service_role_key(configurado, monkeypatch):
    # Sin ella no hay con que leer profiles: la revalidacion corre en el
    # servidor, sin el token de la persona.
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY")
    assert supabase_sesion.configurado() is False


def test_ya_no_hace_falta_la_cadena_de_postgres(configurado, monkeypatch):
    # Pedia la contrasena de la base solo para leer un perfil. Y una cadena
    # mal puesta -la URL del proyecto, con https- dejaba a todos afuera.
    monkeypatch.delenv("SUPABASE_DB_URL", raising=False)
    assert supabase_sesion.configurado() is True
    monkeypatch.setenv("SUPABASE_DB_URL", "https://abcdefghijklmnopqrst.supabase.co")
    assert supabase_sesion.configurado() is True


class _Respuesta:
    def __init__(self, estado, cuerpo):
        self.status_code = estado
        self._cuerpo = cuerpo

    def json(self):
        return self._cuerpo

    def raise_for_status(self):
        import httpx

        if self.status_code >= 400:
            peticion = httpx.Request("GET", "https://ejemplo")
            raise httpx.HTTPStatusError(
                f"{self.status_code}", request=peticion,
                response=httpx.Response(self.status_code, request=peticion),
            )


def test_el_perfil_se_lee_por_la_api_de_supabase(configurado, monkeypatch):
    llamadas = []

    def get_falso(url, **opciones):
        llamadas.append((url, opciones))
        return _Respuesta(200, [perfil_de(permissions=["jarvis.usar"])])

    monkeypatch.setattr(supabase_sesion.httpx, "get", get_falso)
    uuid = "11111111-2222-3333-4444-555555555555"

    datos = supabase_sesion.perfil(uuid)

    assert datos["full_name"] == "Ana Perez"
    url, opciones = llamadas[0]
    assert url == "https://abcdefghijklmnopqrst.supabase.co/rest/v1/profiles"
    assert opciones["params"]["id"] == f"eq.{uuid}"
    assert "permissions" in opciones["params"]["select"]
    assert opciones["headers"]["apikey"] == SERVICE
    assert opciones["headers"]["Authorization"] == f"Bearer {SERVICE}"


def test_un_perfil_que_no_esta_en_la_tabla(configurado, monkeypatch):
    monkeypatch.setattr(supabase_sesion.httpx, "get", lambda url, **o: _Respuesta(200, []))
    assert supabase_sesion.perfil("11111111-2222-3333-4444-555555555555") is None


def test_si_la_api_rechaza_el_pedido_no_entra_nadie(configurado, monkeypatch):
    monkeypatch.setattr(supabase_sesion.httpx, "get", lambda url, **o: _Respuesta(401, {}))
    import httpx

    with pytest.raises(httpx.HTTPStatusError):
        supabase_sesion.perfil("11111111-2222-3333-4444-555555555555")


def test_el_diagnostico_dice_el_codigo_http(configurado, monkeypatch):
    # 401 es la service role mal puesta; 404, que no existe la tabla profiles.
    # Son arreglos distintos y la clase sola no los distingue.
    monkeypatch.setattr(supabase_sesion, "id_de_token",
                        lambda t: "11111111-2222-3333-4444-555555555555")
    monkeypatch.setattr(supabase_sesion.httpx, "get", lambda url, **o: _Respuesta(401, {}))
    supabase_sesion._cache.clear()

    motivo = supabase_sesion.diagnostico("un-token")

    assert motivo.startswith("error-perfil:HTTPStatusError")
    assert "401" in motivo


def test_la_url_del_proyecto_sale_de_la_referencia(configurado):
    assert supabase_sesion.url_proyecto() == "https://abcdefghijklmnopqrst.supabase.co"


def test_un_uuid_invalido_no_llega_a_la_base(configurado):
    # El uuid se interpola en el SQL, asi que tiene que estar comprobado antes.
    with pytest.raises(ValueError):
        supabase_sesion.perfil("'; drop table profiles; --")


def perfil_de(role="agent", permissions=None, platforms=None, nombre="Ana Perez"):
    return {
        "id": "11111111-2222-3333-4444-555555555555",
        "email": "ana@empresa.com",
        "full_name": nombre,
        "role": role,
        "permissions": permissions,
        "platforms": platforms,
    }


def test_con_jarvis_usar_entra_como_usuario():
    usuario = supabase_sesion.usuario_de_perfil(perfil_de(permissions=["jarvis.usar"]))
    assert usuario.rol == "usuario"
    assert usuario.nombre == "Ana Perez"
    assert usuario.id == "sb-11111111-2222-3333-4444-555555555555"


def test_con_jarvis_admin_entra_como_admin():
    usuario = supabase_sesion.usuario_de_perfil(perfil_de(permissions=["jarvis.admin"]))
    assert usuario.rol == "admin"


@pytest.mark.parametrize("role", ["super_admin", "admin"])
def test_los_administradores_de_la_plataforma_son_admin(role):
    assert supabase_sesion.usuario_de_perfil(perfil_de(role=role)).rol == "admin"


def test_sin_permiso_de_jarvis_no_entra():
    assert supabase_sesion.usuario_de_perfil(perfil_de(permissions=["inbox.send"])) is None


def test_un_perfil_viejo_sin_permisos_no_entra():
    # permissions en NULL y platforms de las tres viejas: el catalogo ya no
    # concede jarvis por respaldo, y aqui tampoco.
    sin_migrar = perfil_de(
        permissions=None, platforms=["inbox", "cotizaciones", "cobranzas"]
    )
    assert supabase_sesion.usuario_de_perfil(sin_migrar) is None


def test_sin_nombre_se_usa_la_parte_del_correo():
    anonimo = perfil_de(permissions=["jarvis.usar"], nombre=None)
    assert supabase_sesion.usuario_de_perfil(anonimo).nombre == "ana"


def test_un_perfil_inexistente_no_entra():
    assert supabase_sesion.usuario_de_perfil(None) is None


def test_entrar_con_un_token_bueno(configurado, monkeypatch):
    monkeypatch.setattr(supabase_sesion, "id_de_token",
                        lambda t: "11111111-2222-3333-4444-555555555555")
    monkeypatch.setattr(supabase_sesion, "perfil_cacheado",
                        lambda u: perfil_de(permissions=["jarvis.usar"]))
    assert supabase_sesion.entrar("un-token").rol == "usuario"


def test_entrar_con_un_token_invalido(configurado, monkeypatch):
    monkeypatch.setattr(supabase_sesion, "id_de_token", lambda t: None)
    assert supabase_sesion.entrar("un-token") is None


def test_si_supabase_falla_no_entra_nadie(configurado, monkeypatch):
    def revienta(_):
        raise RuntimeError("Supabase no responde")

    monkeypatch.setattr(supabase_sesion, "id_de_token", revienta)
    # Nunca modo abierto: un fallo deja fuera, no deja pasar.
    assert supabase_sesion.entrar("un-token") is None


def test_con_el_puente_apagado_no_entra_nadie():
    assert supabase_sesion.entrar("un-token") is None


def test_revalidar_devuelve_none_si_le_quitaron_el_permiso(configurado, monkeypatch):
    previo = supabase_sesion.usuario_de_perfil(perfil_de(permissions=["jarvis.usar"]))
    monkeypatch.setattr(supabase_sesion, "perfil_cacheado",
                        lambda u: perfil_de(permissions=["inbox.send"]))
    assert supabase_sesion.revalidar(previo) is None


def test_revalidar_actualiza_el_rol(configurado, monkeypatch):
    previo = supabase_sesion.usuario_de_perfil(perfil_de(permissions=["jarvis.usar"]))
    monkeypatch.setattr(supabase_sesion, "perfil_cacheado",
                        lambda u: perfil_de(permissions=["jarvis.admin"]))
    assert supabase_sesion.revalidar(previo).rol == "admin"


def test_revalidar_ignora_a_los_de_contrasena(configurado):
    from backend import acceso

    de_variable = acceso.Usuario("admin", "Lucas", "admin")
    # No lleva el prefijo: no se toca la base por el.
    assert supabase_sesion.revalidar(de_variable) is de_variable


def test_el_perfil_se_cachea_un_minuto(configurado, monkeypatch):
    llamadas = []

    def contar(uuid):
        llamadas.append(uuid)
        return perfil_de(permissions=["jarvis.usar"])

    supabase_sesion.limpiar_cache()
    monkeypatch.setattr(supabase_sesion, "perfil", contar)

    uuid = "11111111-2222-3333-4444-555555555555"
    supabase_sesion.perfil_cacheado(uuid)
    supabase_sesion.perfil_cacheado(uuid)
    supabase_sesion.perfil_cacheado(uuid)

    # Tres consultas seguidas, una sola ida a la base.
    assert len(llamadas) == 1


def test_el_token_solo_no_autoriza_a_nadie(configurado):
    """usuario_de_token NO confirma el permiso de quien viene de un panel.

    Su permiso vive en profiles, y quien lo confirma es revalidar(). Si esta
    funcion devolviera un rol real, cualquier codigo futuro que la llamara sin
    revalidar le daria acceso a alguien a quien ya se lo quitaron.
    """
    from backend import acceso

    token = acceso.crear_token(acceso.Usuario("sb-abc", "Ana", "usuario"))
    provisional = acceso.usuario_de_token(token)

    assert provisional is not None          # la firma si es buena
    assert provisional.rol == "sin-confirmar"
    assert provisional.rol != "admin"


def test_diagnostico_dice_que_el_puente_esta_apagado():
    # Sin las variables no se puede comprobar a nadie. Es un problema de
    # configuracion, no de la persona: no hay que mandarla a pedir permiso.
    assert supabase_sesion.diagnostico("un-token") == "apagado"


def test_diagnostico_distingue_un_token_invalido(configurado, monkeypatch):
    monkeypatch.setattr(supabase_sesion, "id_de_token", lambda t: None)
    assert supabase_sesion.diagnostico("un-token") == "token"


def test_diagnostico_distingue_la_falta_de_permiso(configurado, monkeypatch):
    monkeypatch.setattr(supabase_sesion, "id_de_token",
                        lambda t: "11111111-2222-3333-4444-555555555555")
    monkeypatch.setattr(supabase_sesion, "perfil_cacheado",
                        lambda u: perfil_de(permissions=["inbox.send"]))
    assert supabase_sesion.diagnostico("un-token") == "permiso"


def test_diagnostico_distingue_un_perfil_que_no_existe(configurado, monkeypatch):
    monkeypatch.setattr(supabase_sesion, "id_de_token",
                        lambda t: "11111111-2222-3333-4444-555555555555")
    monkeypatch.setattr(supabase_sesion, "perfil_cacheado", lambda u: None)
    assert supabase_sesion.diagnostico("un-token") == "sin-perfil"


def test_diagnostico_distingue_un_fallo_de_la_base(configurado, monkeypatch):
    def revienta(_):
        raise RuntimeError("la base no responde")

    monkeypatch.setattr(supabase_sesion, "id_de_token",
                        lambda t: "11111111-2222-3333-4444-555555555555")
    monkeypatch.setattr(supabase_sesion, "perfil_cacheado", revienta)
    assert supabase_sesion.diagnostico("un-token").startswith("error-perfil:")


def test_diagnostico_detecta_una_referencia_con_forma_de_url(configurado, monkeypatch):
    # Pegar la URL entera en SUPABASE_PROJECT_REF es un despiste facil, y su
    # sintoma seria una excepcion de red indistinguible de una caida.
    monkeypatch.setenv("SUPABASE_PROJECT_REF", "https://abcdefghijklmnopqrst.supabase.co")
    assert supabase_sesion.diagnostico("un-token") == "ref-invalida"


def test_diagnostico_dice_en_que_paso_fallo_supabase(configurado, monkeypatch):
    def revienta(_):
        raise RuntimeError("no hay red")

    monkeypatch.setattr(supabase_sesion, "id_de_token", revienta)
    motivo = supabase_sesion.diagnostico("un-token")
    assert motivo.startswith("error-token:")
    assert "RuntimeError" in motivo


def test_un_programmingerror_pelado_trae_su_mensaje(configurado, monkeypatch):
    # psycopg lanza ProgrammingError sin subclase por fallos del lado del
    # cliente, y la clase sola no distingue entre ellos. Su mensaje no lleva
    # secretos y es lo unico que dice que arreglar.
    class ProgrammingError(Exception):
        pass

    def revienta(_):
        raise ProgrammingError(
            "can't change 'read_only' now: connection in transaction status INTRANS"
        )

    monkeypatch.setattr(supabase_sesion, "id_de_token",
                        lambda t: "11111111-2222-3333-4444-555555555555")
    monkeypatch.setattr(supabase_sesion, "perfil_cacheado", revienta)
    motivo = supabase_sesion.diagnostico("un-token")
    assert motivo.startswith("error-perfil:ProgrammingError")
    assert "read_only" in motivo


def test_el_detalle_nunca_lleva_la_service_role_key(configurado, monkeypatch, capsys):
    # Abre la base entera saltandose las reglas de acceso: ni a la persona ni
    # al log.
    class ProgrammingError(Exception):
        pass

    def revienta(_):
        raise ProgrammingError(f"fallo usando la llave {SERVICE}")

    monkeypatch.setattr(supabase_sesion, "id_de_token",
                        lambda t: "11111111-2222-3333-4444-555555555555")
    monkeypatch.setattr(supabase_sesion, "perfil_cacheado", revienta)

    motivo = supabase_sesion.diagnostico("un-token")

    assert SERVICE not in motivo
    assert SERVICE not in capsys.readouterr().out
