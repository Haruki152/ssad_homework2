"""属性定义及取值校验。严格区分整数、文本和枚举，不自动转换类型。"""
class ValidationError(ValueError):
    pass


def allowed_values(definition):
    return [v.strip() for v in (definition.value_domain or "").split(",") if v.strip()]


def validate_definition(name, data_type, value_domain):
    if not isinstance(name, str) or not name.strip():
        raise ValidationError("属性名称不能为空")
    if data_type not in {"text", "int", "enum"}:
        raise ValidationError("属性类型只能是 text、int 或 enum")
    values = [v.strip() for v in (value_domain or "").split(",") if v.strip()]
    if data_type == "enum" and not values:
        raise ValidationError("枚举属性必须定义取值域")
    if data_type == "int":
        for value in values:
            try:
                int(value)
            except ValueError:
                raise ValidationError("整数属性的取值域必须包含整数")


def validate_values(definitions, attrs):
    attrs = {} if attrs is None else attrs
    if not isinstance(attrs, dict):
        raise ValidationError("属性值必须是对象")
    defined = {d.name: d for d in definitions}
    unknown = set(attrs) - set(defined)
    if unknown:
        raise ValidationError("存在未定义的属性: " + ", ".join(sorted(unknown)))
    for definition in definitions:
        name = definition.name
        value = attrs.get(name)
        if definition.required and (
            name not in attrs or value is None or
            (isinstance(value, str) and not value.strip())
        ):
            raise ValidationError(f"必填属性不能为空: {name}")
        if name not in attrs:
            continue
        if value is None:
            raise ValidationError(f"属性 {name} 不接受 null；可选属性可省略")
        if definition.data_type == "int":
            valid_type = type(value) is int
        elif definition.data_type in {"text", "enum"}:
            valid_type = isinstance(value, str)
        else:
            raise ValidationError(f"属性 {name} 的定义类型无效")
        if not valid_type:
            raise ValidationError(f"属性 {name} 必须是 {definition.data_type} 类型")
        allowed = allowed_values(definition)
        if allowed:
            if definition.data_type == "int":
                try:
                    valid_value = value in [int(v) for v in allowed]
                except ValueError:
                    raise ValidationError(f"属性 {name} 的整数取值域无效")
            else:
                valid_value = value in allowed
            if not valid_value:
                raise ValidationError(f"属性 {name} 超出取值域")
