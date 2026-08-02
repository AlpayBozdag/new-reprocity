
[app]

title = AYNA V5.3
package.name = aynav53
package.domain = org.alpay

source.dir = .
source.include_exts = py,kv,png,jpg,jpeg,csv,json,txt

version = 5.3

requirements = python3,kivy==2.3.1

orientation = portrait
fullscreen = 0

android.api = 36
android.minapi = 24
android.ndk = 29
android.ndk_api = 24
android.archs = arm64-v8a

android.permissions = READ_MEDIA_IMAGES,READ_MEDIA_VIDEO

p4a.bootstrap = sdl2

[buildozer]

log_level = 2
warn_on_root = 1
