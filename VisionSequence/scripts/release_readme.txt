VisionSequence {{VERSION}}  (built {{BUILT}})
=====================================================

This folder is a complete, self-contained VisionSequence station for 64-bit Windows 10/11 or
Windows Server 2016+. It brings its own Python; nothing else has to be installed and no
internet connection is needed.

Contents
--------
  python\            embedded Python 3.12 with every runtime package preinstalled
  apps\ config\      the platform
  frontend\dist\     the web interface (served by the platform itself)
  docs\              the manuals (start with docs\index.html)
  scripts\           install.ps1, vsctl.ps1, service.ps1, proxy.ps1
  tools\             nssm.exe (Windows service wrapper), caddy.exe (HTTPS proxy), vc_redist.x64.exe
  examples\plugins\  sample plugins to copy from
  capture-client\    the camera-PC program offered for download on the Integration > Capture page
  release.json       version and build information

Install (setup wizard)
----------------------
Run VisionSequence-Setup-{{VERSION}}.exe. It asks for the station id, the host names / IP addresses
client PCs will use, the LAN subnet allowed through the firewall, the HTTPS mode and the first
administrator account, then installs everything into C:\VisionSequence and starts the services.

Install (this zip, by hand)
---------------------------
1. Unpack this folder anywhere (e.g. C:\Temp\VisionSequence-{{VERSION}}).
2. Open PowerShell as Administrator and run:

     Set-ExecutionPolicy -Scope Process Bypass
     .\scripts\install.ps1 -Root C:\VisionSequence -StationId ST01 -HostNames vision-st01,192.168.1.10 -Subnet 192.168.1.0/24 -Https internal

   Options: -Https custom -Cert fullchain.pem -Key private.key | -Https none (plain HTTP on port 8000)
            -NoTcpAuth (devices that cannot send AUTH) | -Mode task -Interactive -User DOMAIN\name -Password ***
            (cameras attached to the server PC itself, SDK needs a signed-in session)
3. The summary at the end shows the web address, the administrator account and how to read the keys.

After the install
-----------------
  C:\VisionSequence\vsctl.cmd status | logs | doctor | backup | env list | plugins install <zip> | dl install <pack.zip>
  Client PCs (HTTPS internal): import C:\VisionSequence\certs\root.crt into "Trusted Root Certification
  Authorities" (vsctl certs export / vsctl certs import), then open https://<host name>/.
  Camera PCs: Integration > Capture > Download, unpack, point it at <server>:9100 with the capture key.
  Upgrades: vsctl update VisionSequence-<new>-win64.zip     Roll back: vsctl rollback

Layout
------
  C:\VisionSequence\app\{{VERSION}}\   this folder (immutable; upgrades add a sibling and switch "current")
  C:\VisionSequence\current\           junction to the running version
  C:\VisionSequence\data\              database, assets, archive, logs, backups, downloads
  C:\VisionSequence\plugins\           your plugins (with wheels\ for offline dependencies)
  C:\VisionSequence\packs\             deep-learning add-on packs (reinstalled automatically on update)
  C:\VisionSequence\certs\             root.crt for client PCs, custom certificate
  C:\VisionSequence\.env               station configuration and keys

Ports
-----
  443 (or 8000 without HTTPS) web interface and HTTP API   9000 TCP commands   9100 capture clients
  Modbus TCP slave connections use the port set on each connection.

Full documentation: docs\deployment.html (install, HTTPS, clients, upgrade), docs\index.html (everything).
