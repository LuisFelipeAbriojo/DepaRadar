# Modelo de negocio de DepaRadar

## Quién paga
El **inversionista minorista** de Lima: alguien con US$30–60k de ahorro que quiere comprar 1 o 2 departamentos para alquilar y no sabe si "el número cierra".

**Por qué paga:** el depa mediano de Lima Moderna se pide en US$182.9k, pero solo cuadra (VAN ≥ 0 con 80 % de crédito al 6.3 % y un costo de oportunidad de 10 %) si se compra a ~US$127.8k. Una sola negociación guiada por DepaRadar puede ahorrarle miles de dólares; la suscripción cuesta S/ 39 al mes.

## Precio (freemium)
| Plan | Precio | Incluye |
|---|---|---|
| **Gratis** | S/ 0 | Radar de 1 distrito y las 3 mejores oportunidades; evaluador con supuestos por defecto. |
| **Pro** | **S/ 39/mes** (~US$11.4 con IGV) | 10 distritos, evaluaciones ilimitadas, precio máximo a ofrecer, agente-chat con Gemini, alertas de nuevas oportunidades. |
| Informe suelto | S/ 19 por depa | PDF del análisis para el banco o la negociación. |

Roadmap: plan para corredores (S/ 149/mes) y comisiones por referir clientes hipotecarios precalificados a bancos.

## Costo por usuario Pro al mes (con 100 usuarios)
Precios de `gemini-3.5-flash-lite` en la API de Google (nivel estándar, nov-2026): **US$0.30 por millón de tokens de entrada y US$2.50 por millón de salida**.

| Concepto | Cálculo | US$/usuario/mes |
|---|---|---|
| Gemini lee los avisos | Medido: 1,769 avisos = 385k tokens de entrada + 193k de salida = **US$0.60** por dataset completo. Con caché solo se leen los avisos nuevos (~20 % por semana) → ~US$0.50/mes, compartido por todos. | 0.005 |
| Agente-chat | ~4k tokens de entrada + 600 de salida por pregunta = US$0.0027 × 100 preguntas | 0.27 |
| Servidor | Hoy gratis (Streamlit Community Cloud). Con usuarios: ~US$25/mes (app + base de datos) | 0.25 |
| Pasarela de pago | ~4 % de US$11.4 (Culqi / Mercado Pago) | 0.45 |
| **Total** | | **≈ US$0.98** |

**Ingreso neto por usuario:** S/ 39 ÷ 1.18 (IGV) ÷ 3.43 = **US$9.64** → **margen bruto ≈ 90 %**.

Para bajar costos: la extracción de avisos puede ir por la Batch API de Gemini (mitad de precio) y se puede limitar el agente a 100 preguntas al mes en el plan Pro.

## Cómo conseguir los primeros usuarios
1. Contenido semanal con datos reales: "¿Este depa de Miraflores cuadra? 🧮" (TikTok, LinkedIn, Instagram).
2. Grupos de inversión inmobiliaria en Facebook y LinkedIn; red de exalumnos de la UP.
3. Las conversaciones con usuarios (`docs/research/`) cierran con: "¿pagarías S/ 39 al mes?".

## Por qué ahora
Hace tres años, leer y estructurar el texto de miles de avisos requería analistas o modelos caros; hoy cuesta **US$0.60** con Gemini flash-lite. El BCRP publica tasas en una API abierta y Streamlit permite desplegar gratis: un estudiante puede construir y operar esto por menos de US$1 por usuario.
