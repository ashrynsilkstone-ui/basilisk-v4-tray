Name:           basilisk-v4-tray
Version:        %{tray_version}
Release:        1
Summary:        KDE tray status and settings for the Razer Basilisk V4 Pro
License:        LicenseRef-Unspecified
URL:            https://github.com/ashrynsilkstone-ui/basilisk-v4-tray
Source0:        %{name}-%{version}.tar.gz
BuildArch:      noarch
Requires:       python3 >= 3.9
Requires:       python3-dbus
Requires:       python3-openrazer
Requires:       python3-pyside6
Requires:       qt6-qtwayland

# This package stores portable Python source outside site-packages.
%global __brp_python_bytecompile %{nil}

%description
Watch battery, DPI stage and polling rate on a HyperSpeed-connected Basilisk V4 Pro.
The KDE tray app configures DPI stages, polling, power and per-zone lighting through
a compatible OpenRazer driver and daemon.

%prep
%setup -q

%install
sh packaging/stage.sh "%{buildroot}"

%files
%{_bindir}/basilisk-v4-tray
%{_datadir}/applications/local.razer.BasiliskTray.desktop
%{_datadir}/basilisk-v4-tray/
%config(noreplace) %{_sysconfdir}/xdg/autostart/local.razer.BasiliskTray.desktop
%{_docdir}/basilisk-v4-tray/
