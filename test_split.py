line = "inherit_memory(content_ids = [1,2,3] , extra_param=5)"
funcname, args_str = line.split("(", 1)
args_str = args_str.rstrip(")")
kwargs = {}
args = args_str.split(",")

for arg in args:
    if "=" in arg and "[" in arg and "]" not in arg: # list argument split by comma
        key, value = arg.split("=", 1)
        list_values = value.strip().lstrip('[')
        for next_arg in args[args.index(arg)+1:]:
            if "]" in next_arg:
                list_values += "," + next_arg.strip().rstrip("]")
                break
            else:
                list_values += "," + next_arg.strip()
        kwargs[key.strip()] = list_values
    elif "=" in arg:
        key, value = arg.split("=", 1)
        kwargs[key.strip()] = value.strip()

print(funcname.strip())
print(kwargs)