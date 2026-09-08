# Proposed additions

The current foundation is delivered: ordinary engine modules, a headless
simulation, explicit PvP rules, bounded desktop stepping, spatial collision
queries, per-world cache invalidation, and focused regression coverage.
[ARCHITECTURE.md](ARCHITECTURE.md) describes what exists and its limits.

The items below are proposals, not implemented features or release promises.

## First priorities

1. **Deterministic replay and save/resume.** Record versioned initial settings,
   seed, timestep, and accepted commands; serialize complete state for saves,
   including RNG state, pending actions, projectiles, and timers. Verify that a
   resumed run and an uninterrupted run reach matching state hashes. This
   gives players resumable battles and developers reproducible bug reports.

2. **Network output queues and draw results.** Give each connection a bounded
   writer worker so a slow reader cannot stall simulation. Coalesce replaceable
   snapshots while preserving ordered gameplay events. Carry a draw outcome
   through server results and the desktop UI instead of labeling both sides
   defeated. Test slow peers, simultaneous elimination, and cleanup.

3. **Scenario and weapon schemas.** Move configurable scenario, roster, weapon,
   and objective data behind versioned schemas with clear validation errors.
   Preserve current defaults and provide migration checks before allowing
   external content. This creates a stable basis for modding and an editor.

## Next extensions

4. **Smoother, resumable multiplayer.** Add snapshot sequence numbers,
   interpolation, delta encoding with full-state resynchronization, and
   acknowledged commands. Reconnect should restore the same player slot with a
   bounded grace period and authenticated resume token. Measure bandwidth and
   recovery under delay, interruption, and stale messages.

5. **Rendering culling and profiling.** Measure frame-time distributions and
   individual terrain, unit, effect, and UI costs. Cull off-screen work and
   invalidate cached drawing only when relevant state changes. Compare the
   same seeded battles at multiple resolutions and unit counts; retain visual
   smoke coverage and report regressions as well as gains.

6. **Scenario editor.** Build on the validated data schemas: terrain painting,
   spawn zones, objectives, roster selection, and an immediate playtest loop.
   Start with import/export and undo before adding campaign tools. Edited
   scenarios should run through the same simulation and stress validation.

7. **Smaller engine and frontend APIs.** Replace retained private compatibility
   chains gradually, split large rule/data and UI modules by responsibility,
   and document stable system interfaces. Preserve compatibility at the facade
   while new callers use explicit modules; evaluate ECS-style storage only if
   profiling or new game requirements justify it.
