Name:           screen-toolbox
Version:        0.1.0
Release:        1%{?dist}
Summary:        Prints com anotações e gravação de tela com teclas e cliques
License:        GPL-3.0-or-later
URL:            https://github.com/nicolas/screen-toolbox
Source0:        %{name}-%{version}.tar.gz
BuildArch:      noarch

BuildRequires:  make
Requires:       python3 >= 3.10
Requires:       python3-gobject
Requires:       python3-cairo
Requires:       gtk4 >= 4.10
Requires:       libadwaita >= 1.5
Requires:       gstreamer1
Requires:       gstreamer1-plugins-base
Requires:       gstreamer1-plugins-good
Requires:       pipewire-gstreamer
Requires:       xdg-desktop-portal
# H.264/MP4 (RPM Fusion); sem ele o app grava em WebM (VP9)
Recommends:     gstreamer1-plugins-ugly
Recommends:     gstreamer1-plugin-libav

%description
Captura área ou tela inteira, edita com caneta, setas, formas, texto,
desfoque e pixelização, e grava a tela com áudio opcional exibindo as
teclas pressionadas e os cliques do mouse no vídeo.

%prep
%autosetup

%build

%install
make install DESTDIR=%{buildroot} PREFIX=%{_prefix}

%files
%{_bindir}/screen-toolbox
%{_datadir}/screen-toolbox/
%{_datadir}/applications/io.github.nicolas.ScreenToolbox.desktop
%{_datadir}/icons/hicolor/scalable/apps/io.github.nicolas.ScreenToolbox*.svg
%{_datadir}/metainfo/io.github.nicolas.ScreenToolbox.metainfo.xml

%changelog
* Mon Oct 26 2026 Nicolas <nicolastavaress.dev@gmail.com> - 0.1.0-1
- Primeira versão
