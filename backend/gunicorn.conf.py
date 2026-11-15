# Read by gunicorn from the working directory (/app in the image), so it
# applies both to start.sh and to the Helm chart's own gunicorn command.
# gunicorn skips names it does not know, so this is safe on older versions.

# gunicorn 27 opens a control socket under /app/.gunicorn by default. The
# image runs as a non-root user (and the chart with a read-only root
# filesystem), so it cannot be created and gunicorn logs an error at every
# start. SerOps does not use the control interface.
control_socket_disable = True
