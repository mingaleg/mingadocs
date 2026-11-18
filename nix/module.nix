{ self }:
{
  config,
  lib,
  pkgs,
  ...
}:

let
  cfg = config.services.mingadocs;
  stateDir = "/var/lib/mingadocs";
in
{
  options.services.mingadocs = {
    enable = lib.mkEnableOption "mingadocs, the document scanning and ARN label web app";

    package = lib.mkOption {
      type = lib.types.package;
      default = self.packages.${pkgs.stdenv.hostPlatform.system}.default;
      defaultText = lib.literalExpression "mingadocs.packages.\${system}.default";
    };

    mediaDir = lib.mkOption {
      type = lib.types.str;
      default = "${stateDir}/media";
      description = ''
        Scanned pages and finished document PDFs. The SQLite database always
        stays in ${stateDir}, on the assumption that this may be a big, slow
        disk. The service will not start while the directory's file system
        is not mounted.
      '';
    };

    listen = {
      address = lib.mkOption {
        type = lib.types.str;
        default = "127.0.0.1";
      };
      port = lib.mkOption {
        type = lib.types.port;
        default = 8095;
      };
    };

    allowedHosts = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      example = [ "docs.example.lan" ];
      description = "Host names the app answers to (Django's ALLOWED_HOSTS).";
    };

    secretKeyFile = lib.mkOption {
      type = lib.types.str;
      description = "Runtime path to Django's secret key (e.g. an agenix secret). Passed via LoadCredential.";
    };

    threads = lib.mkOption {
      type = lib.types.ints.positive;
      default = 8;
      description = ''
        gunicorn threads. There is always exactly one worker process: scan,
        OCR and hardware-probe jobs run as threads inside it.
      '';
    };

    staticDir = lib.mkOption {
      type = lib.types.path;
      readOnly = true;
      default = "${cfg.package}/share/mingadocs/static";
      defaultText = lib.literalExpression "\"\${package}/share/mingadocs/static\"";
      description = ''
        Collected static files, for the front web server to serve at /static/.
        It also has to serve `mediaDir` at /media/: with DEBUG off the app
        serves neither.
      '';
    };
  };

  config = lib.mkIf cfg.enable {
    users.users.mingadocs = {
      isSystemUser = true;
      group = "mingadocs";
      home = stateDir;
    };
    users.groups.mingadocs = { };

    systemd.services.mingadocs = {
      description = "mingadocs document scanning web app";
      wantedBy = [ "multi-user.target" ];
      wants = [ "network-online.target" ];
      after = [ "network-online.target" ];
      # Without this, an unmounted media disk would make the app quietly
      # write new scans onto whatever is underneath the mount point.
      unitConfig.RequiresMountsFor = [ cfg.mediaDir ];

      # scanimage, for the SANE scanner. CUPS is reached over its socket.
      path = [ pkgs.sane-backends ];

      environment = {
        MINGADOCS_DEBUG = "0";
        MINGADOCS_DB_PATH = "${stateDir}/db.sqlite3";
        MINGADOCS_MEDIA_ROOT = cfg.mediaDir;
        MINGADOCS_ALLOWED_HOSTS = lib.concatStringsSep "," cfg.allowedHosts;
        MINGADOCS_SECRET_KEY_FILE = "%d/secret-key";
      };

      serviceConfig = {
        User = "mingadocs";
        Group = "mingadocs";
        StateDirectory = "mingadocs";
        StateDirectoryMode = "0750";
        UMask = "0027";
        LoadCredential = [ "secret-key:${cfg.secretKeyFile}" ];

        ExecStartPre = [
          # Created on every start, not by tmpfiles at boot: the disk may only
          # get mounted (or be replaced by an empty one) later. "+" lifts the
          # file system restrictions for this step, and the "-" on
          # ReadWritePaths below lets its sandbox be set up while the
          # directory doesn't exist yet; every later step is spawned with a
          # fresh sandbox in which it does. Group-readable, so a web server
          # (or a file share) in the group can read documents without being
          # able to change them.
          "+${pkgs.coreutils}/bin/install -d -m 0750 -o mingadocs -g mingadocs ${cfg.mediaDir}"
          "${cfg.package}/bin/mingadocs-manage migrate --noinput"
        ];
        ExecStart = lib.escapeShellArgs [
          "${cfg.package}/bin/mingadocs-gunicorn"
          "--bind"
          "${cfg.listen.address}:${toString cfg.listen.port}"
          "--workers"
          "1"
          "--threads"
          (toString cfg.threads)
          # A scan request can wait on the scanner for a long time.
          "--timeout"
          "300"
          "--access-logfile"
          "-"
        ];
        Restart = "on-failure";
        RestartSec = 5;

        ReadWritePaths = [ "-${cfg.mediaDir}" ];
        NoNewPrivileges = true;
        PrivateTmp = true;
        PrivateDevices = true;
        ProtectSystem = "strict";
        ProtectHome = true;
        ProtectClock = true;
        ProtectHostname = true;
        ProtectKernelLogs = true;
        ProtectKernelModules = true;
        ProtectKernelTunables = true;
        ProtectControlGroups = true;
        RestrictAddressFamilies = [
          "AF_UNIX"
          "AF_INET"
          "AF_INET6"
        ];
        RestrictNamespaces = true;
        RestrictRealtime = true;
        RestrictSUIDSGID = true;
        LockPersonality = true;
        # Not MemoryDenyWriteExecute: pypdfium2 goes through ctypes callbacks,
        # which need writable+executable trampolines.
        SystemCallArchitectures = "native";
      };
    };
  };
}
