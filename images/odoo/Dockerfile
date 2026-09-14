FROM odoo:18.0

USER root
COPY entrypoint.sh /usr/local/bin/odoo-entrypoint.sh
RUN chmod 0755 /usr/local/bin/odoo-entrypoint.sh
USER odoo

ENTRYPOINT ["/usr/local/bin/odoo-entrypoint.sh"]
