"""The container image's fixed layout. The Dockerfile copies this file to
layout_pinned.py, which is what makes it apply -- see layout.py. Nothing
imports this module directly.

    /app/config/config.yaml   ./config/config.yaml, mounted writable: the
                              Settings screen rewrites it in place. Its
                              folder makes /app the project directory, so
                              relative paths resolve the same as in a checkout
    /app/config/secret.key    ./config/secret.key, mounted read-only
    /app/data                 docker.data_dir, the only writable mount
    0.0.0.0                   inside the container's own network namespace;
                              what is reachable from outside is
                              docker.bind_address
"""
CONFIG_FILE = "/app/config/config.yaml"
APP_DIR = "/app/data"
HOST = "0.0.0.0"
