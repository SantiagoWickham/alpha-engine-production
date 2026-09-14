# ALPHA ENGINE V12.0 — RETURN FIRST

Esta carpeta inicia un motor nuevo de investigación. **No modifica V10.4, GitHub, Google Sheets, Apps Script, Forward ni las claves existentes.**

## Principio rector

1. Primero demostrar y medir capacidad predictiva de retorno futuro.
2. Después transformar esa señal en una cartera sin destruirla.
3. Riesgo, cobertura, liquidez y ejecución se evalúan después como restricciones/diagnósticos, no como señales de retorno salvo que los datos prueben que mejoran el retorno OOS.
4. Ningún peso de factor, score o cartera se fija "a ojo". Todo parámetro elegible debe ser estimado o seleccionado sólo con datos de entrenamiento/validación temporal.
5. El holdout futuro no se usa para elegir modelos.

## Qué NO hace Phase 0

No crea una nueva fórmula Alpha todavía. Hacerlo antes de conocer exactamente el dataset reutilizable repetiría el error de elegir pesos arbitrarios. Phase 0 inventaría nada: audita los datos y deja un inventario reproducible que se usa para diseñar el motor V12.

## Qué conservar de V10.4

- `.env` y secretos: se reutilizan más adelante; no se copian ni imprimen en Phase 0.
- `data/`: se conserva íntegro y se trata como read-only durante investigación.
- Google Sheets / Apps Script: se considera infraestructura de entrada/salida, no motor de decisión.
- nomenclatura de tickers, identificadores y datasets: se preserva siempre que sea técnicamente posible.

## Preparación exacta

1. Descomprimí esta carpeta en:
   `C:\Users\santi\OneDrive\Escritorio\ALPHA ENGINE\ALPHA_ENGINE_V12_RETURN_FIRST`
2. Copiá tu carpeta histórica `data` dentro de esa carpeta. Debe quedar:
   `...\ALPHA_ENGINE_V12_RETURN_FIRST\data\`
3. NO copies `.env` todavía. Phase 0 no necesita claves.
4. Si tenés una exportación local del Google Sheets, ponela en `inputs\`. Si no, no pasa nada.
5. Abrí PowerShell dentro de la carpeta y ejecutá:
   `powershell -ExecutionPolicy Bypass -File .\RUN_PHASE_0.ps1`

## Qué devolver

Subí estos archivos de `outputs\`:

- `phase0_summary.txt`
- `data_inventory.json`
- `data_inventory.csv`
- `repo_inventory.json` (si encontró el repo V10.4)
- `spreadsheet_inventory.json` (si encontró un xlsx en inputs)

Con eso se construye Phase 1: búsqueda de señales de retorno y targets sin pesos manuales.
