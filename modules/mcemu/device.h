int DeviceWritePage(int mc_num, void *buf, u32 page_num);
int DeviceReadPage(int mc_num, void *buf, u32 page_num);
#ifdef BDM_DRIVER
/* count pages from page_num, in one device write */
int DeviceWritePages(int mc_num, void *buf, u32 page_num, u32 count);
#endif
void DeviceShutdown(void);
