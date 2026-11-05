# First-boot game counter: issue #287

The report names RiptOPL v1.2.0-Beta-4045 and USB, but supplies no ELF hash,
edition, theme, configuration, or precise source commit. A matching version
number alone does not identify the reporter's artifact.

The four public RiptOPL release manifests inspected on 2026-11-02 (Pacific)
identify source 22c319f72c046a583917fb73852f7de1d359bd8d, including the
rolling-lite USB build. That source already contains the count-refresh change
merged through RiptOPL #271 (24b950d466b677f48f0111f0e819d91963f65b5d).
The corresponding legacy OPL change is #1232. Do not classify #287 as an
outdated build or claim that #271 resolved the reporter's observation.

The follow-up fixes an independently confirmed allocation failure: the count
initializer used a one-byte empty seed, then replaced it with 60 bytes. If
the replacement allocation failed, rendering could write beyond the seed.
The counter now allocates its final buffer directly, frees the metadata on
buffer failure, and renders nothing when allocation fails. It needs two
allocations at theme load and none during rendering.

The host test executes both allocations failing, successful initialization,
zero and delayed counts, unchanged selection, Mixed-view population, rescans,
and simulated count changes using the same CFG uid. It does not execute
the game-return lifecycle or a physical USB scan. This is host evidence only.

For reporter acceptance, identify the exact ELF/hash and theme, capture the
initial display and a later scan without moving selection, and compare the
same artifact/configuration on cold boot and after IGR. A remaining incorrect
count needs its actual value and the source list's count. No physical-console
acceptance or proof of the reporter's root cause is claimed.

References:
- https://github.com/NathanNeurotic/RiptOPL/issues/287
- https://github.com/NathanNeurotic/RiptOPL/pull/271
- https://github.com/NathanNeurotic/Open-PS2-Loader/pull/1232
- https://github.com/NathanNeurotic/RiptOPL/releases/tag/rolling-lite
