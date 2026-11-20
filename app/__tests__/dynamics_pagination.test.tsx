import React from 'react';
import { act, create, type ReactTestRenderer } from 'react-test-renderer';
import { FlatList } from 'react-native';
import DynamicsScreen from '../features/dynamics/DynamicsScreen';
import { getDynamics } from '../features/dynamics/dynamics';

jest.mock('react-native', () => ({
  ActivityIndicator: 'ActivityIndicator', FlatList: 'FlatList', Image: 'Image',
  KeyboardAvoidingView: 'KeyboardAvoidingView', Platform: { OS: 'android' },
  Pressable: 'Pressable', RefreshControl: 'RefreshControl', StyleSheet: { create: (styles: unknown) => styles },
  Text: 'Text', TextInput: 'TextInput', TouchableOpacity: 'TouchableOpacity', View: 'View',
}));
jest.mock('react-native-safe-area-context', () => ({ useSafeAreaInsets: () => ({ top: 0, bottom: 0 }) }));
jest.mock('../features/dynamics/dynamics', () => ({ getDynamics: jest.fn() }));

it('列表到底后保留首页并追加下一页，末页停止请求', async () => {
  const post = {
    author_type: 'user', author_id: 'alice', author_name: 'Alice', owner_user_id: 'alice',
    visibility: 'private', image_refs: [], source_type: 'user', source_id: null, allow_comment: true,
    memory_policy: null, memory_status: null, memory_error: null, reply_status: null, reply_error: null,
    status: 'published', created_at: null, updated_at: null, comment_count: 0,
  };
  jest.mocked(getDynamics)
    .mockResolvedValueOnce({ items: [{ ...post, id: '2', content: '新动态', cursor: 'b' }], has_more: true, next_cursor: 'b' })
    .mockResolvedValueOnce({ items: [{ ...post, id: '1', content: '旧动态', cursor: 'a' }], has_more: false, next_cursor: null });
  const markRead = jest.fn().mockResolvedValue(undefined);
  let tree!: ReactTestRenderer;
  await act(async () => {
    tree = create(<DynamicsScreen session={{ username: 'alice', token: 'token', serverUrl: 'https://test' }}
      markRead={markRead} onClose={jest.fn()} />);
  });
  const list = () => tree.root.findByType(FlatList).props;
  expect(list().data).toHaveLength(1);
  await act(async () => { await list().onEndReached(); });
  expect(getDynamics).toHaveBeenLastCalledWith('alice', 'token', 20, 'b');
  expect(list().data.map((item: { content: string }) => item.content)).toEqual(['新动态', '旧动态']);
  await act(async () => { await list().onEndReached(); });
  expect(getDynamics).toHaveBeenCalledTimes(2);
  expect(markRead).toHaveBeenCalledTimes(1);
  act(() => tree.unmount());
});
