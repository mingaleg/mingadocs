{ pkgs, self }:

# Boots the NixOS module and checks the production path end to end: migrations
# run, gunicorn serves pages with DEBUG off, static files were collected - and
# that a media disk which isn't there keeps the app down instead of letting it
# write scans onto the disk underneath the mount point.
let
  common = {
    imports = [ self.nixosModules.default ];

    environment.etc."mingadocs-secret-key".text = "vm-test-secret-key-not-a-real-one";
    services.mingadocs = {
      enable = true;
      mediaDir = "/mnt/media/mingadocs";
      allowedHosts = [ "localhost" ];
      secretKeyFile = "/etc/mingadocs-secret-key";
    };

    # No real hardware here: don't spend the test waiting on scanimage / CUPS.
    systemd.services.mingadocs.environment.MINGADOCS_SKIP_HARDWARE_PROBE = "1";
  };
in
pkgs.testers.nixosTest {
  name = "mingadocs";

  nodes.machine = {
    imports = [ common ];
    virtualisation.fileSystems."/mnt/media" = {
      device = "tmpfs";
      fsType = "tmpfs";
    };
  };

  # The media disk is configured like a removable/optional one ("nofail"), but
  # its device never shows up - e.g. the external drive is unplugged.
  nodes.nodisk = {
    imports = [ common ];
    virtualisation.fileSystems."/mnt/media" = {
      device = "/dev/disk/by-label/not-plugged-in";
      fsType = "ext4";
      options = [
        "nofail"
        "x-systemd.device-timeout=5s"
      ];
    };
  };

  testScript =
    { nodes, ... }:
    let
      cfg = nodes.machine.services.mingadocs;
      port = toString cfg.listen.port;
    in
    ''
      start_all()

      with subtest("serves the app with DEBUG off"):
          machine.wait_for_unit("mingadocs.service")
          machine.wait_for_open_port(${port})
          machine.succeed("curl -sf -H 'Host: localhost' http://127.0.0.1:${port}/ | grep -q '<html'")
          # Unknown Host header -> 400, i.e. ALLOWED_HOSTS is in force.
          machine.succeed("test $(curl -s -o /dev/null -w '%{http_code}' -H 'Host: evil' http://127.0.0.1:${port}/) = 400")
          machine.succeed("test -s /var/lib/mingadocs/db.sqlite3")
          machine.succeed("test -f ${cfg.staticDir}/arnlabels/app.css")
          machine.succeed("stat -c '%U:%G %a' /mnt/media/mingadocs | grep -qx 'mingadocs:mingadocs 750'")

      with subtest("unmounting the media disk takes the app down with it"):
          machine.succeed("systemctl stop mnt-media.mount")
          machine.fail("systemctl is-active mingadocs.service")
          machine.succeed("systemctl start mingadocs.service")
          machine.wait_for_open_port(${port})

      with subtest("a missing media disk keeps the app down"):
          nodisk.wait_for_unit("multi-user.target")
          nodisk.fail("systemctl start mingadocs.service")
          nodisk.fail("systemctl is-active mingadocs.service")
          # Nothing was created on the root disk where the media disk should be.
          nodisk.fail("test -e /mnt/media/mingadocs")
    '';
}
