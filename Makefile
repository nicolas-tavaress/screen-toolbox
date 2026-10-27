APP_ID  := io.github.nicolas.ScreenToolbox
VERSION := 0.1.0
PREFIX  ?= /usr/local
DESTDIR ?=
SHARE   := $(DESTDIR)$(PREFIX)/share

.PHONY: run dev logs install uninstall deb clean

run:
	./bin/screen-toolbox

# modo desenvolvimento: logs detalhados e coloridos no terminal
dev:
	./bin/screen-toolbox --dev

# acompanha o arquivo de log (também funciona com o app instalado)
logs:
	tail -f $${XDG_STATE_HOME:-$$HOME/.local/state}/screen-toolbox/screen-toolbox.log

install:
	install -d $(SHARE)/screen-toolbox
	cp -r screen_toolbox $(SHARE)/screen-toolbox/
	find $(SHARE)/screen-toolbox -name '__pycache__' -prune -exec rm -rf {} +
	install -Dm755 bin/screen-toolbox $(DESTDIR)$(PREFIX)/bin/screen-toolbox
	install -Dm644 data/$(APP_ID).desktop $(SHARE)/applications/$(APP_ID).desktop
	install -Dm644 data/$(APP_ID).svg $(SHARE)/icons/hicolor/scalable/apps/$(APP_ID).svg
	install -Dm644 data/$(APP_ID)-tray.svg $(SHARE)/icons/hicolor/scalable/apps/$(APP_ID)-tray.svg
	install -Dm644 data/$(APP_ID)-tray-recording.svg $(SHARE)/icons/hicolor/scalable/apps/$(APP_ID)-tray-recording.svg
	install -Dm644 data/$(APP_ID).metainfo.xml $(SHARE)/metainfo/$(APP_ID).metainfo.xml

uninstall:
	rm -rf $(SHARE)/screen-toolbox
	rm -f $(DESTDIR)$(PREFIX)/bin/screen-toolbox \
	      $(SHARE)/applications/$(APP_ID).desktop \
	      $(SHARE)/icons/hicolor/scalable/apps/$(APP_ID).svg \
	      $(SHARE)/icons/hicolor/scalable/apps/$(APP_ID)-tray.svg \
	      $(SHARE)/icons/hicolor/scalable/apps/$(APP_ID)-tray-recording.svg \
	      $(SHARE)/metainfo/$(APP_ID).metainfo.xml

# Pacote .deb simples (Debian/Ubuntu), sem precisar de debhelper
deb:
	rm -rf build/deb
	$(MAKE) install DESTDIR=build/deb PREFIX=/usr
	install -d build/deb/DEBIAN
	sed 's/@VERSION@/$(VERSION)/' packaging/debian/control > build/deb/DEBIAN/control
	dpkg-deb --root-owner-group --build build/deb build/screen-toolbox_$(VERSION)_all.deb

clean:
	rm -rf build
	find . -name '__pycache__' -prune -exec rm -rf {} +
