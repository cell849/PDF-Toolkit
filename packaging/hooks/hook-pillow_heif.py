"""Include optional codec modules and Windows wheel DLLs in the desktop build."""

from PyInstaller.utils.hooks import collect_all, collect_delvewheel_libs_directory

datas, binaries, hiddenimports = collect_all("pillow_heif")
datas, binaries = collect_delvewheel_libs_directory("pillow_heif", datas=datas, binaries=binaries)
hiddenimports.append("_pillow_heif")
