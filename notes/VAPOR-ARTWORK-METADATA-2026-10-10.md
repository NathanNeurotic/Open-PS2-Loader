# Vapor artwork and metadata report, October 10, 2026

Continuation is PR #894 (`fix/bdm-hdd-library-recovery`, base `rebuild/main`).
Local HEAD was eight commits behind GitHub and was fast-forwarded from cec486b4
to c4751f11943c0b7a77f0193417ca00f6390c01e7. Untracked `build/` was preserved.
At that head, formatting, build-flavours, Korium PR hardware-test build and Korium
background diagnostic workflows succeeded. CodeRabbit's status says "Review paused";
this does not establish approval. No console pass is implied by those builds.

The supplied Discord screenshot reports Medium artwork sizing, a 16:9 default,
a request for better disc art, and missing Title/Genre/Release/Developer/Description
values while labels and Size render. Treat the message as report evidence.

Source confirms Medium (30 pixels) coverflow center enlargement and 16:9 defaults.
Use Large (45 pixels) and 4:3 for fresh configurations, retaining saved overrides.
This enlargement is specific to coverflow; it does not resize the theme's ICO image.

Attribute text reads case-sensitive metadata keys from the per-game CFG. Game name
(`#Name`) and size are supplied separately. Add a display-only fallback from absent
or empty `Title` to `#Name`, preserving explicit metadata and avoiding CFG writes.
No source-backed reason exists to invent the other fields. The screenshot alone
cannot distinguish a missing CFG from missing fields or a failed source-path read.

PNG decoding retains IHDR dimensions and uses linear filtering. Enlarging a low-detail
ICO cannot add detail. No decoder or VRAM-budget change is justified by this screenshot.
Inspect the actual ICO dimensions/encoding and rendered theme dimensions before any
quality change; a higher-detail source image may be sufficient within texture limits.

Console acceptance remains open: fresh and saved 4:3/16:9 configurations, Large and
saved Medium coverflow settings, metadata CFG present/absent/empty Title, explicit
Title precedence, Info selection changes, and the Korium overlay artifact. Verify
metadata on the same game source used by the report before calling all fields fixed.
