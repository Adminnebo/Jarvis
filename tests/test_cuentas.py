from backend import cuentas


def test_crear_organizacion_da_de_alta_a_su_primera_cuenta():
    usuario = cuentas.crear_organizacion("Acme", "Lucas", "lucas@acme.com", "una-clave-larga")

    assert usuario.id.startswith(cuentas.PREFIJO)
    assert usuario.nombre == "Lucas"
    assert usuario.rol == "usuario"
    assert usuario.organizacion_id
    assert cuentas.nombre_organizacion(usuario.organizacion_id) == "Acme"


def test_la_primera_cuenta_administra_su_organizacion():
    usuario = cuentas.crear_organizacion("Acme", "Lucas", "lucas@acme.com", "una-clave-larga")
    assert cuentas.es_admin_org(usuario.id) is True


def test_falta_de_datos_se_rechaza():
    import pytest

    with pytest.raises(cuentas.ErrorDeCuenta):
        cuentas.crear_organizacion("", "Lucas", "lucas@acme.com", "una-clave-larga")
    with pytest.raises(cuentas.ErrorDeCuenta):
        cuentas.crear_organizacion("Acme", "Lucas", "no-es-un-correo", "una-clave-larga")
    with pytest.raises(cuentas.ErrorDeCuenta):
        cuentas.crear_organizacion("Acme", "Lucas", "lucas@acme.com", "corta")


def test_no_se_puede_repetir_el_correo():
    import pytest

    cuentas.crear_organizacion("Acme", "Lucas", "lucas@acme.com", "una-clave-larga")
    with pytest.raises(cuentas.ErrorDeCuenta):
        cuentas.crear_organizacion("Otra", "Otro", "lucas@acme.com", "otra-clave-larga")


def test_entrar_con_la_contrasena_correcta():
    cuentas.crear_organizacion("Acme", "Lucas", "lucas@acme.com", "una-clave-larga")
    usuario = cuentas.entrar("lucas@acme.com", "una-clave-larga")
    assert usuario is not None
    assert usuario.nombre == "Lucas"


def test_entrar_con_contrasena_incorrecta_no_entra():
    cuentas.crear_organizacion("Acme", "Lucas", "lucas@acme.com", "una-clave-larga")
    assert cuentas.entrar("lucas@acme.com", "no-es") is None
    assert cuentas.entrar("no-existe@acme.com", "una-clave-larga") is None


def test_agregar_usuario_suma_gente_a_la_misma_organizacion():
    admin = cuentas.crear_organizacion("Acme", "Lucas", "lucas@acme.com", "una-clave-larga")
    miembro = cuentas.agregar_usuario(
        admin.organizacion_id, "Ana", "ana@acme.com", "otra-clave-larga"
    )

    assert miembro.organizacion_id == admin.organizacion_id
    assert cuentas.es_admin_org(miembro.id) is False

    ids = {m["email"] for m in cuentas.miembros(admin.organizacion_id)}
    assert ids == {"lucas@acme.com", "ana@acme.com"}


def test_usuario_de_id_no_sirve_para_una_cuenta_borrada():
    assert cuentas.usuario_de_id("no-existe") is None


def test_id_crudo_distingue_el_origen():
    assert cuentas.id_crudo("u-abc123") == "abc123"
    assert cuentas.id_crudo("sb-abc123") is None
    assert cuentas.id_crudo("jorge") is None
