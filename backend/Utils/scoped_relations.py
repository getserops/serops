"""Limit a serializer's writable relations to the requester's rows."""


def limit_relations(fields, request, **specs):
    """``specs``: field name -> function(user, organisation) returning the
    allowed queryset. A field id from another organisation then fails as
    DRF's ordinary "object does not exist". With no organisation in context
    the querysets are empty, so nothing can be written.
    """
    user = getattr(request, 'user', None)
    organisation = getattr(user, 'organisation', None)
    for name, allowed in specs.items():
        field = fields.get(name)
        if field is None or field.read_only:
            continue
        target = getattr(field, 'child_relation', field)
        target.queryset = allowed(user, organisation) if organisation else target.queryset.model.objects.none()
    return fields
