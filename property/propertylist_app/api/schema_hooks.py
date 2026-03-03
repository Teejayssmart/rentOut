def _is_enveloped_schema(schema: dict, components: dict) -> bool:
    """
    Detect if a schema is already an envelope (directly or via $ref to a component).
    Envelope means: has properties ok + data (message optional).
    """
    if not isinstance(schema, dict):
        return False

    # Direct envelope
    props = schema.get("properties") if isinstance(schema.get("properties"), dict) else None
    if props and "ok" in props and "data" in props:
        return True

    # $ref to component
    ref = schema.get("$ref")
    if isinstance(ref, str) and ref.startswith("#/components/schemas/"):
        name = ref.split("/")[-1]
        comp = (components or {}).get("schemas", {}).get(name)
        if isinstance(comp, dict):
            comp_props = comp.get("properties") if isinstance(comp.get("properties"), dict) else None
            if comp_props and "ok" in comp_props and "data" in comp_props:
                return True

    return False


def _wrap_schema(schema: dict) -> dict:
    return {
        "type": "object",
        "properties": {
            "ok": {"type": "boolean"},
            "message": {"type": "string", "nullable": True},
            "data": schema,
        },
        "required": ["ok", "data"],
    }


def wrap_success_responses(result, generator, request, public):
    """
    drf-spectacular postprocessing hook:
    Wrap all 2xx JSON response schemas in {ok, message, data}, unless already wrapped.
    """
    components = result.get("components", {})
    paths = result.get("paths", {})

    for path_item in paths.values():
        if not isinstance(path_item, dict):
            continue

        for method_item in path_item.values():
            if not isinstance(method_item, dict):
                continue

            responses = method_item.get("responses", {})
            if not isinstance(responses, dict):
                continue

            for status_code, resp in list(responses.items()):
                # Only 2xx
                if not (isinstance(status_code, str) and status_code.startswith("2")):
                    continue
                if status_code == "204":
                    continue

                if not isinstance(resp, dict):
                    continue

                content = resp.get("content", {})
                if not isinstance(content, dict):
                    continue

                app_json = content.get("application/json")
                if not isinstance(app_json, dict):
                    continue

                schema = app_json.get("schema")
                if not isinstance(schema, dict):
                    continue

                if _is_enveloped_schema(schema, components):
                    continue

                app_json["schema"] = _wrap_schema(schema)

    return result