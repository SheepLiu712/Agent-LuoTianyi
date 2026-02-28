from fastapi import UploadFile
import base64
from PIL import Image
import io
import os
import datetime

async def get_image_bytes_and_base64(upload_file: UploadFile):
    # 1. 读取原始字节
    await upload_file.seek(0)
    original_bytes = await upload_file.read()
    
    try:
        # 2. 使用 Pillow 打开图片
        # BytesIO 将字节流包装成类似文件的对象
        img = Image.open(io.BytesIO(original_bytes))
        
        # 3. 强制转换格式：转为 RGB（处理透明度或多帧问题）并保存为 JPEG
        output_buffer = io.BytesIO()
        if img.mode in ("RGBA", "P"): # 处理带透明度的图片
            img = img.convert("RGB")

        # 压缩图片大小
        origin_width, origin_height = img.size
        # 短边压缩为 27*28 像素
        target_short_side = 27 * 28
        if origin_width < origin_height and origin_width > target_short_side:
            new_width = target_short_side
            new_height = int(origin_height * (target_short_side / origin_width)) // 28 * 28 # 高度也要是 28 的倍数，方便vlm处理
        elif origin_height <= origin_width and origin_height > target_short_side:
            new_height = target_short_side
            new_width = int(origin_width * (target_short_side / origin_height)) // 28 * 28
        
        img = img.resize((new_width, new_height))
        
        # 将图片保存到内存缓冲区，格式设为 JPEG
        img.save(output_buffer, format="JPEG", quality=85)
        processed_bytes = output_buffer.getvalue()
        
        # 4. 生成 Base64
        image_base64 = base64.b64encode(processed_bytes).decode("utf-8")
        return processed_bytes, f"data:image/jpeg;base64,{image_base64}"
        
    except Exception as e:
        print(f"图片转换失败: {e}")
        # 如果转换失败，降级处理：尝试直接传原图 Base64（虽然大概率还是报错）
        return original_bytes, f"data:image/jpeg;base64,{base64.b64encode(original_bytes).decode('utf-8')}"
    
async def save_image(user_id: str, image_bytes: bytes, postfix: str) -> str:
    '''
    将图片保存到本地，并返回文件路径。    
    :param user_id: 用户ID，用于生成唯一文件名
    :type user_id: str
    :param image_bytes: 图片字节数据
    :type image_bytes: bytes
    :return: 保存的图片文件路径
    :rtype: str
    '''
    try:
        save_dir = os.path.join("data", "images", user_id)
        os.makedirs(save_dir, exist_ok=True)
        
        # File name handling (replace invalid chars for windows/linux)
        safe_time = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        file_path = os.path.join(save_dir, f"{safe_time}.{postfix}")
        with open(file_path, "wb") as f:
            f.write(image_bytes)
        return file_path
    except Exception as e:
        print(f"图片保存失败: {e}")
        return ""

def get_postfix(file_name: str) -> str:
    '''
    获取文件后缀名
    :param file_name: 文件名
    :type file_name: str
    :return: 文件后缀名
    :rtype: str
    '''
    return os.path.splitext(file_name)[1]