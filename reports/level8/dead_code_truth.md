# Architectural cleanup truth

No code was deleted based solely on absent textual references.

The bundled interpreter under `tools/python` is infrastructure, not an architectural module; graph traversal now prunes this exact subtree and retains other operator tools. Graph file hashing is streamed to avoid loading heap dumps or databases entirely into RAM.

The ON_DEMAND activation contracts for knowledge relationships and goal dependencies previously promised zero rows. Read-only production counts were respectively 1 edge, 1 contradiction and 6 dependencies. The contracts retain reachable producers/readers and their proof tests; observed relationships no longer contradict perpetual-empty assertions.

A complete runtime-supported inventory of dead handlers, unused flags, duplicate services and legacy routes remains PENDING. No table or runtime state was deleted to make an audit pass.
