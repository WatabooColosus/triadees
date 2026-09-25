# Respuesta web: diagnóstico y corrección preparada

Observación: 2026-09-21 16:57 -05:00. Rama main, HEAD
9c1fd1187760e42335f58dbfa0bbe153fd52fc01. `git fetch origin` y
`git rev-list --left-right --count HEAD...origin/main`: 0/0.

El detector literal no reconocía «quiero que busques en internet». Se amplió
para conjugaciones y se excluyeron negativas explícitas. El prompt distingue
fuentes de instrucciones y exige citas y límites de verificación. Una petición
web explícita sin fuentes, tras el filtro existente de relevancia, termina con
un aviso de verificación fallida en lugar de publicar recuerdos del modelo.
La protección se aplica después de las transformaciones de expresión y antes
de persistir la respuesta. No modifica respuestas bloqueadas ni pendientes de
aprobación. El filtro de aprendizaje/relevancia existente se conserva.

Prueba de red directa, sin crear runs ni modificar la base operativa:
`guarded_web_research('5 presidentes de Latinoamerica actuales', timeout=5)`.
Resultado: status=ok, search_provider=curated_and_wikipedia_fallback,
source_count=3; URLs de Cartoon Network, Disney Channel y Paramount Networks
Americas en Wikipedia. Son resultados irrelevantes: este status no certifica
una respuesta factual ni que el proveedor de búsqueda general sea operativo.
Queda pendiente mejorar el proveedor general y verificar el flujo desplegado.

Validación aislada:
`python -m pytest tests/test_guarded_web.py tests/test_autonomous_research.py tests/test_expression_cortex_runner.py tests/test_runner_mvp.py -q --basetemp=<ruta absoluta nueva dentro de artifacts/audit-20260921>`
30 pruebas pasaron. Incluyen la frase del usuario, negativas explícitas,
rechazo de fuentes irrelevantes y una respuesta obsoleta simulada que no se
publica cuando la búsqueda falla. Ruff pasó sobre los cinco archivos afectados.
Los primeros intentos de pruebas se corrigieron por usar un nombre reservado
de pytest y un basetemp relativo incompatible con el aislamiento del proyecto.

No se reinició la API. La recarga requiere la autorización pendiente conforme
a AGENTS.md. No se afirma validación del chat desplegado. No hubo commit ni push.
El umbral 0,96 no garantiza exactitud de información obtenida de internet.

Diff exacto acumulado de los cinco archivos (guarded_web y su prueba ya tenían
cambios anteriores): artifacts/audit-20260921/web-response-fix.patch.
Estado completo: artifacts/audit-20260921/web-response-status.txt.
