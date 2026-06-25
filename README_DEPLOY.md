# Uso local en disco

## Archivos principales

- `app.py`: aplicacion Streamlit.
- `requirements.txt`: dependencias Python para instalar en la maquina local.
- `.gitignore`: evita mezclar bases locales, backups, excels y entorno virtual.

## Importante sobre la base de datos

La aplicacion trabaja solamente con la base local:

```text
database/schema.db
```

No utiliza `DATABASE_URL`, no usa PostgreSQL y no depende de secretos externos.

## Usuario administrador inicial

Si la base esta vacia, la aplicacion crea automaticamente un usuario local:

```text
Usuario: admin
Password temporal: admin
```

Ese usuario queda obligado a cambiar la contrasena en el primer ingreso.

## Inicio local

1. Abrir una terminal en la carpeta del proyecto.
2. Ejecutar `streamlit run app.py` o hacer doble click en `Iniciar_ControlHavanna.bat`.
3. Mantener `database/schema.db` dentro del proyecto para conservar los datos.
