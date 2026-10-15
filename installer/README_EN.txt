Rise and Fall Remaster 1.0 - Setup
by Alexander West - thewest.cc/raf

What it does
- Finds your installed "Rise and Fall: Civilization at War" (Russian version 1.15).
- Copies it into a new folder (default: "Rise and Fall Remaster" next to the original).
  The original game is only read, never changed.
- Builds the remaster in the copy from your own game files: borderless fullscreen, smooth
  scrolling, wider zoom (slider in Options > Interface), ultra graphics, mipmaps, new shaders,
  optional HD textures (upscaled on your graphics card), harder AI with personalities, better
  unit AI, unit limit 10000, the "Survival" mode and co-op maps.
- Creates shortcuts (play, host/join a network game, uninstall).

The installer contains no game files. You need your own copy of the game.

Network games
- At the end the installer shows a gameplay fingerprint (also in REMASTER.txt in the game
  folder). All players need the same fingerprint, otherwise the game breaks off.
- "Host network game" opens a LAN lobby directly, "Join network game" asks for the host's IP.

Uninstall
- Start menu "Uninstall Rise and Fall Remaster", Windows Settings > Apps, or Uninstall.bat in
  the remaster folder. It deletes the remaster folder and shortcuts and restores the registry
  values the installer changed.
- Note: the original and the remaster share the game settings in the registry (resolution,
  graphics), so the original uses them too while the remaster is installed.

Graphics card
- The remaster uses DXVK 3.1.1 (Direct3D 9 on Vulkan). DXVK needs Vulkan 1.3 and some newer
  driver extensions (for example VK_KHR_maintenance6), so a current graphics card with a current
  driver. The installer checks this. Without it the game runs on the normal Windows Direct3D 9
  (no d3d9.dll and dxvk.conf in the game folder). A driver update and a new install bring DXVK in.
- If the game does not start with DXVK, delete d3d9.dll and dxvk.conf in the remaster folder.

Problems
- The log is in %TEMP%\RaF-Remaster-Setup.log.

Licenses
- Remaster code: MIT (RaF-Remaster-MIT.txt). Bundled programs and their licenses: folder
  "licenses" or "Remaster-Licenses" in the game folder (DXVK, texconv/DirectXTex, Real-ESRGAN
  ncnn Vulkan + model, ncnn, Python, NumPy, Pillow, pefile, Tcl/Tk, PyInstaller).
