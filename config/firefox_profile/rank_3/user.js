user_pref("browser.shell.checkDefaultBrowser", false);
user_pref("browser.startup.homepage_override.mstone", "ignore");
user_pref("browser.aboutwelcome.enabled", false);
user_pref("datareporting.policy.dataSubmissionEnabled", false);
user_pref("datareporting.policy.firstRunURL", "");
user_pref("browser.sessionstore.resume_from_crash", false);
user_pref("app.update.auto", false);
user_pref("app.update.enabled", false);
user_pref("browser.download.useDownloadDir", true);
user_pref("browser.download.folderList", 2);
user_pref("browser.download.save_converter_index", 1);
user_pref("browser.download.manager.addToRecentDocs", false);
user_pref("browser.tabs.warnOnClose", false);
user_pref("browser.tabs.warnOnCloseOtherTabs", false);
user_pref("browser.warnOnQuit", false);
user_pref("view_source.wrap_long_lines", false);
// DISK CACHE OFF.  Measured: a single 3-card run grew this profile's
// cache2/ to 139 MB, and on a disk that was already at 100% Firefox's
// content process died mid-run -- which looked like "no job card found"
// because the window had quietly gone. The collector re-reads nothing, so
// a disk cache buys it nothing and costs it the run.
user_pref("browser.cache.disk.enable", false);
user_pref("browser.cache.disk.capacity", 0);
user_pref("browser.cache.disk.smart_size.enabled", false);
user_pref("browser.cache.memory.enable", true);
user_pref("browser.cache.memory.capacity", 65536);
user_pref("browser.sessionstore.interval", 600000);
user_pref("places.history.enabled", false);
user_pref("browser.download.dir", "/home/ubuntu/new_indeed_script/Temp_Data/rank_3");
