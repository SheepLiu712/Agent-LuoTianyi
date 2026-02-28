import { local_config } from '@/config';
import * as FileSystem from 'expo-file-system/legacy';
import React, { useEffect, useState } from 'react';
import { ActivityIndicator, Image, ImageStyle, StyleProp, View } from 'react-native';
import { getImage, ImageResponse, updateImagePath } from '../utils/getHistory';
import { auth } from './auth';

const ERROR_IMAGE_URI = Image.resolveAssetSource(local_config.ERROR_IMAGE).uri;

interface CachedImageProps {
    message_id: string;      // 服务器图片地址
    localUri: string;       // 预期的本地缓存路径
    style?: StyleProp<ImageStyle>;
    maxWidth?: number;
    maxHeight?: number;
}

export const CachedImage: React.FC<CachedImageProps> = ({ message_id, localUri, style, maxWidth = 200, maxHeight = 200 }) => {
    const [imgSource, setImgSource] = useState<string | null>(null);
    const [loading, setLoading] = useState(true);
    const [imageSize, setImageSize] = useState<{ width: number, height: number } | null>(null);



    useEffect(() => {
        let isMounted = true;

        // 根据原始图片尺寸和最大限制计算最终显示尺寸
        const calculateImageSize = (originalWidth: number, originalHeight: number) => {
            let finalWidth = originalWidth;
            let finalHeight = originalHeight;

            // 如果宽度超过最大值，按比例缩小
            if (finalWidth > maxWidth) {
                const ratio = maxWidth / finalWidth;
                finalWidth = maxWidth;
                finalHeight = finalHeight * ratio;
            }

            // 如果高度超过最大值，按比例缩小（基于上一步可能缩小过的结果）
            if (finalHeight > maxHeight) {
                const ratio = maxHeight / finalHeight;
                finalHeight = maxHeight;
                finalWidth = finalWidth * ratio;
            }

            setImageSize({ width: finalWidth, height: finalHeight });
        };

        const loadImg = async () => {
            try {
                // 1. 检查本地是否存在
                const fileInfo = await FileSystem.getInfoAsync(localUri);
                if (fileInfo.exists) {
                    if (isMounted) setImgSource(fileInfo.uri);
                    Image.getSize(fileInfo.uri, (width, height) => {
                        if (isMounted) calculateImageSize(width, height);
                    }, (error) => {
                        console.warn("获取图片尺寸失败:", error);
                        if (isMounted) calculateImageSize(maxWidth, maxHeight);
                    });
                }
                else {
                    throw new Error('本地文件不存在');
                }
            } catch (e) {
                console.warn("CachedImage 加载失败，尝试从服务器获取:", e);
                try {
                    const result: ImageResponse = await getImage(auth.username, auth.message_token, message_id);
                    if (result.success && result.newClientPath) {
                        // 3. 成功获取并缓存图片后，更新服务器记录的路径
                        updateImagePath(auth.username, auth.message_token, message_id, result.newClientPath);
                        if (isMounted) setImgSource(result.newClientPath);
                        Image.getSize(result.newClientPath, (width, height) => {
                            if (isMounted) calculateImageSize(width, height);
                        }, (error) => {
                            console.warn("获取图片尺寸失败:", error);
                            if (isMounted) calculateImageSize(maxWidth, maxHeight);
                        });
                    }
                    else {
                        throw new Error('图片获取失败');
                    }
                } catch (e) {
                    console.error("CachedImage 从服务器获取失败:", e);
                    if (isMounted) setImgSource(ERROR_IMAGE_URI);
                }
            } finally {
                if (isMounted) setLoading(false);
            }
        };

        loadImg();
        return () => { isMounted = false; }; // 防止组件卸载后还在设置状态
    }, [message_id, localUri, maxWidth, maxHeight]);



    if (loading) {
        return (
            <View style={[style, { justifyContent: 'center', alignItems: 'center', backgroundColor: '#f0f0f0' }]}>
                <ActivityIndicator size="small" color="#999" />
            </View>
        );
    }

    return <Image
        source={{ uri: imgSource || ERROR_IMAGE_URI }}
        style={[style, imageSize ? { width: imageSize.width, height: imageSize.height } : { width: maxWidth, height: maxHeight }]}
        resizeMode='cover'
    />;
};