# Compressed PS2 images: ZSO, CSO and CHD

Support depends on where the image is read and which program decompresses it.

| Source and core | What to use |
| --- | --- |
| Local folder source or SMB, OPL core | ISO or ZSO; see the [ZSO conversion instructions](../README.md#zso-format). |
| Local source, Neutrino core | Plain ISO. Neutrino does not decompress ZSO, CSO or CHD files itself. |
| UDPFS **Files**, Neutrino core | A compatible PC server can decompress CSO/ZSO/CHD and advertise a virtual `.iso`. The PS2 reads that ISO view. |
| UDPFS IMG / UDPBD | A served disk image containing the supported game layout; individual compressed-file serving is a UDPFS Files feature. |

## Trying a compressed game with PS2-Servers over UDPFS Files

1. Start with an ISO that already launches successfully, so the network and
   Neutrino configuration are known to work.
2. Place the compressed game under `DVD/` or `CD/` in the folder served by
   PS2-Servers, just as you would the original ISO. Keep its real `.cso`, `.zso`
   or `.chd` extension. Avoid a same-named ISO beside it: both would advertise
   the same virtual filename.
3. In Desktop/Core PS2-Servers, check **Compression support**. CSO is built in;
   ZSO needs LZ4 and CHD needs libchdr. The release bundles these optional
   libraries; the running build's support panel is the check that matters.
   Edge supports CSO and ZSO, with no CHD decoder.
4. Use **UDPFS** with **Access: Files** in RiptOPL. Refresh the game list after
   the server starts. A supported compressed image appears as an ISO because
   the server presents its decompressed contents to Neutrino.
5. Launch normally. If it is absent, first check the server's compression
   support and startup log. Renaming a compressed container to `.iso` does not
   convert it or enable support.

The files remain compressed on the PC; the server decompresses requested data
before sending it. This saves PC storage, not network traffic. Compression can
add PC CPU and random-read cost, so game performance still needs testing.

See [PS2-Servers compression support](https://github.com/NathanNeurotic/PS2-Servers#compression)
and its [optional dependency guide](https://github.com/NathanNeurotic/PS2-Servers/blob/main/docs/optional-compression-dependencies.md).
Other UDPFS servers can have different capabilities. This guide does not add
direct compressed-file decoding to RiptOPL or Neutrino.
