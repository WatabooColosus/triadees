# Research fallback

El commit base `8b82562` añadió recuperación mediante fuentes curadas y
Wikipedia cuando falla la búsqueda primaria. La auditoría confirma que aún falta
completar fuentes parciales, centralizar política, deduplicar por URL/hash/
dominio-título, emitir métricas y distinguir todos los estados solicitados.

Ese cambio pertenece al PR 7 y no se mezcla con el núcleo temporal de esta fase.
Recuperar fuentes nunca equivale a contrastar ni a promover conocimiento.
