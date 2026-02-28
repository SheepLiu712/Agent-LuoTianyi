import os
import datetime


def image_preprocess(image_path: str) -> str:
    with open(image_path, "rb") as f:
        image_data = f.read()

    # get new file path
    cwd = os.getcwd()
    postfix = os.path.splitext(image_path)[1]
    new_file_path = os.path.join(cwd, "temp", "images", datetime.datetime.now().strftime("%Y%m%d%H%M%S")+postfix)
    os.makedirs(os.path.dirname(new_file_path), exist_ok=True)
    with open(new_file_path, "wb") as f:
        f.write(image_data)
    image_type = "image/png"  # default type
    if postfix.lower() in [".jpg", ".jpeg"]:
        image_type = "image/jpeg"
    elif postfix.lower() == ".gif":
        image_type = "image/gif"