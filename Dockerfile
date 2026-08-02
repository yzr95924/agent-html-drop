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

# Non-root user. uid 1000 is the typical host user uid — bind-mounted
# ./data Just Works if its owner is uid 1000; otherwise override `user:` in
# compose or chown ./data to 1000 (design §15.5 uid-alignment note).
USER ahd

EXPOSE 8765
ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["serve"]
