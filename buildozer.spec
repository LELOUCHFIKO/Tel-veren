[app]
title = Tel veren ve vermeyen
package.name = telverenvermeyen
package.domain = az.mmu
source.dir = .
source.include_exts = py,png,jpg,csv
version = 1.0
requirements = python3,kivy==2.3.0
orientation = portrait
fullscreen = 0
android.permissions = WRITE_EXTERNAL_STORAGE,READ_EXTERNAL_STORAGE
android.api = 31
android.minapi = 21
android.archs = arm64-v8a
android.accept_sdk_license = True

[buildozer]
log_level = 2
warn_on_root = 1
