# Hardware-test branch harness.
# GNU make reads this file before Makefile. Apply the isolated test patch once,
# then continue through the repository's normal build.
APA_HDL_TEST_PATCH := tools/test-patches/apa-hdl-diagnostic.patch
_apa_hdd_test_apply := $(shell patch -p1 --forward --silent < $(APA_HDL_TEST_PATCH) >/dev/null 2>&1 || true)

include Makefile
