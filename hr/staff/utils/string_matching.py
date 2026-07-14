from rapidfuzz import process

def get_fuzzy_matches(input_string, queryset, field_name="name", threshold=80):
    if not input_string or not isinstance(input_string, str):
        return []

    items = [item.strip() for item in input_string.split(",") if item.strip()]
    
    obj_map = {str(getattr(obj, field_name)).lower(): obj for obj in queryset}
    choices = list(obj_map.keys())
    
    matched_objects = []

    for item in items:
        result = process.extractOne(item.lower(), choices)
        if result:
            best_match, score, index = result
            if score >= threshold:
                matched_objects.append(obj_map[best_match])
    
    return matched_objects

# from rapidfuzz import process

# def get_fuzzy_matches_from_map(input_string, choices_map, threshold=80):
#     """
#     input_string: "Main Campuss, West Wing"
#     choices_map: {"main campus": <Object>, "west wing": <Object>}
#     """
#     if not input_string or not isinstance(input_string, str) or input_string.lower() in ["nan", "none", ""]:
#         return []

#     items = [item.strip() for item in input_string.split(",") if item.strip()]
#     choices_names = list(choices_map.keys())
#     matched_objects = []

#     for item in items:
#         result = process.extractOne(item.lower(), choices_names)
#         if result:
#             best_match, score, _ = result
#             if score >= threshold:
#                 matched_objects.append(choices_map[best_match])
    
#     return matched_objects