# agent-html-drop daemon image (design §15).
#
# Self-contained: the daemon serves everything — including /files/* — over
# plain HTTP. Put your own nginx (TLS terminator) in front and reverse-proxy
# to 127.0.0.1:8765. See docs/design.md §15.
#
# Source is stdlib-only; python:3.12 ships stdlib tomllib → zero runtime deps.
FROM python:3.12-slim

ENV PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1 \
    XDG_CONFIG_HOME=/data/config

# gosu for the entrypoint's privilege drop: it starts as root, chowns the
# bind-mounted /data to the app uid, then re-execs the daemon as non-root
# `ahd`. ./data then works for any host-side owner — no manual chown (§15.5).
RUN apt-get update \
 && apt-get install -y --no-install-recommends gosu \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY src/agent_html_drop /app/src/agent_html_drop
COPY docker/entrypoint.sh /app/docker/entrypoint.sh

# Convenience wrapper so `docker exec ... agent-html-drop <subcommand>` works
# (docker exec does not go through ENTRYPOINT).
RUN printf '#!/bin/sh\nexec python3 -m agent_html_drop "$@"\n' \
        > /usr/local/bin/agent-html-drop \
 && chmod +x /usr/local/bin/agent-html-drop /app/docker/entrypoint.sh \
 && groupadd --system --gid 1000 ahd \
 && useradd --system --uid 1000 --gid ahd --no-create-home ahd \
 && mkdir -p /data/docroot /data/config \
 && chown -R ahd:ahd /data

# No USER directive — the entrypoint runs as root just long enough to chown
# /data to uid 1000, then `exec gosu ahd` drops to non-root for the daemon.
# The daemon itself never runs as root (§15.5).
EXPOSE 8765
ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["serve"]
