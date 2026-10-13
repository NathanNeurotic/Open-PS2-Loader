# Trust anchors for the RA HTTPS lookup

The only certificates the RA edition's HTTPS client trusts. retroachievements.org currently chains to
**GTS Root R4** (leaf <- Google Trust Services WE1 <- GTS Root R4). The other Google roots cover a
key-type rotation, and the ISRG roots cover a move to Let's Encrypt.

| File | Subject | SHA-256 (DER) | Expires | Source |
| --- | --- | --- | --- | --- |
| `gtsr1.der` | GTS Root R1 | `d947432abde7b7fa90fc2e6b59101b1280e0e1c7e4e40fa3c6887fff57a7f4cf` | 2036-06-22 | <https://pki.goog/repo/certs/gtsr1.der> |
| `gtsr2.der` | GTS Root R2 | `8d25cd97229dbf70356bda4eb3cc734031e24cf00fafcfd32dc76eb5841c7ea8` | 2036-06-22 | <https://pki.goog/repo/certs/gtsr2.der> |
| `gtsr3.der` | GTS Root R3 | `34d8a73ee208d9bcdb0d956520934b4e40e69482596e8b6f73c8426b010a6f48` | 2036-06-22 | <https://pki.goog/repo/certs/gtsr3.der> |
| `gtsr4.der` | GTS Root R4 | `349dfa4058c5e263123b398ae795573c4e1313c83fe68f93556cd5e8031b3c7d` | 2036-06-22 | <https://pki.goog/repo/certs/gtsr4.der> |
| `isrgrootx1.der` | ISRG Root X1 | `96bcec06264976f37460779acf28c5a7cfe8a3c0aae11a8ffcee05c0bddf08c6` | 2035-06-04 | <https://letsencrypt.org/certs/isrgrootx1.der> |
| `isrg-root-x2.der` | ISRG Root X2 | `69729b8e15a86efc177a57afb7171dfc64add28c2fca8cf1507e34453ccb1470` | 2040-09-17 | <https://letsencrypt.org/certs/isrg-root-x2.der> |

Each file was downloaded from the issuer on 2026-10-13, and its fingerprint was found in the Mozilla
root store (certifi 2026.02.25). `.github/scripts/test_mbedtls_vendor.py` pins the same fingerprints
in its own source. The Makefile turns each file into `ratls_root_<name>.c` with `bin2c` (RA builds
only).
