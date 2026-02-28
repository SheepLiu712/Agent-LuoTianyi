import { useCallback, useState } from "react";
import { ChatMessage } from "../components/ChatBubbles";
import { server_config } from "../config/index";
import { getHistory } from "../utils/getHistory";

export function useHistoryLogic(addHistoryMessage: (messages: ChatMessage[]) => void) {
    const [history_start_index, setHistoryStartIndex] = useState(-1); 
    const [historyLoading, setHistoryLoading] = useState(false);

    const loadHistory = useCallback(async (
        username: string,
        token: string,
        count: number = server_config.LOAD_HISTORY_COUNT 
    ): Promise<void> => {
        // 如果正在加载或已经到头，则直接返回
        if (historyLoading || history_start_index === 0) {
            return;
        }

        setHistoryLoading(true); 
        try {
            // 获取历史记录数据
            const result = await getHistory(username, token, count, history_start_index); 
            setHistoryStartIndex(result.startIndex); 

            if (result.messages.length > 0) {
                // 将新加载的历史消息添加到现有消息列表的末尾
                addHistoryMessage(result.messages);
            }
        } catch (error) {
            console.error('加载历史记录流程出错:', error);
        } finally {
            setHistoryLoading(false); 
        }
    }, [historyLoading, history_start_index, addHistoryMessage]); // 核心依赖项

    return {
        history_start_index,
        historyLoading,
        loadHistory,
    }; //
}