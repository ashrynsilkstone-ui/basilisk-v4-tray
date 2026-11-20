Name:           basilisk-v4-tray
Version:        %{tray_version}
Release:        1
Summary:        KDE tray status and settings for OpenRazer mice and receivers
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
View battery, DPI and polling rate for the selected OpenRazer device.
Configure the supported sensor, power, lighting and receiver settings.

%prep
%setup -q

%install
sh packaging/stage.sh "%{buildroot}"

%files
%{_bindir}/basilisk-v4-tray
%{_datadir}/applications/local.razer.BasiliskTray.desktop
%{_datadir}/basilisk-v4-tray/
/usr/lib/udev/rules.d/69-basilisk-v4-tray.rules
%config(noreplace) %{_sysconfdir}/xdg/autostart/local.razer.BasiliskTray.desktop
%{_docdir}/basilisk-v4-tray/
