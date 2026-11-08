/**
 * Android 连续中文两端对齐（issue #313）。
 *
 * React Native 的 `textAlign: 'justify'` 在 Android 上只拉伸普通空格，
 * 连续中文的自动折行不会贴齐右边缘。这里只做一遍测量：
 *
 * 1. 用一个不可见 Text 让系统按当前宽度自然折行，拿到每行文本和行宽；
 * 2. 把行文本映射回原始 runs，按 `(容器宽度 - 自然宽度) / (字符数 - 1)`
 *    给每一行加 `letterSpacing`。
 *
 * 最终仍然只渲染一个外层 `Text`，行与行之间是嵌套 span + `\n`，
 * 因此行高、字体缩放、选中和读屏行为与原来的 RN Text 一致，不会因为
 * 拆成多个 Text 而在行间多出 includeFontPadding。
 *
 * 正常的中文段落按上述公式处理即可，不存在行尾空格。只有当折行点恰好
 * 落在空格上（如纯英文段落、中英混排的空格恰在行尾）时，行尾才会带着
 * 原文中的一个空格。对这种特定情况，决定是不做额外的排除宽度处理：
 * 依据是 spec"不删除字符"——排除或补偿空格宽度相当于把该字符当作
 * 不存在，等于删除原文。
 */

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { StyleSheet, Text, useWindowDimensions, View } from 'react-native';
import type { LayoutChangeEvent, TextLayoutEvent } from 'react-native';

import {
  buildJustifiedLines,
  buildLineDescriptors,
  splitTrailingChar,
} from '../utils/agreement_justify';
import type { JustifiedLine, JustifyRun } from '../utils/agreement_justify';

interface Props {
  /** 已按显式换行拆好的单行 runs：[文本, 是否加粗]。 */
  runs: readonly (readonly [string, boolean])[];
  fontSize: number;
  lineHeight: number;
  color: string;
}

// native：单行或测量不可信，直接沿用系统 justify 的占位 Text。
type Result = 'measuring' | 'native' | JustifiedLine[];

interface JustifyState {
  key: string;
  result: Result;
}

// 最终 Text 比容器宽 2dp：给 letterSpacing 的亚像素累加误差留余量，避免
// 最后一个字被系统换成下一行。行尾字符独立成 span、不追加行尾间距后，
// 行宽精确等于容器宽，缓冲只需覆盖这类误差；多出的宽度在容器外，不可见。
const FINAL_WIDTH_BUFFER = 2;

function renderRuns(runs: readonly JustifyRun[], letterSpacing?: number) {
  return (
    <Text style={letterSpacing ? { letterSpacing } : undefined}>
      {runs.map((run, index) => (
        <Text key={index} style={run.bold ? styles.bold : undefined}>
          {run.text}
        </Text>
      ))}
    </Text>
  );
}

// 字间距只加在相邻字符之间的间隙里：行尾字符单独成 span、不追加间距，
// 使行宽精确等于容器宽。行尾字符保持自己的粗体样式。
function renderJustifiedLine(line: JustifiedLine) {
  if (line.letterSpacing > 0) {
    const { head, tail } = splitTrailingChar(line.runs);
    if (head.length > 0 && tail) {
      return (
        <React.Fragment>
          <Text style={{ letterSpacing: line.letterSpacing }}>
            {head.map((run, index) => (
              <Text key={index} style={run.bold ? styles.bold : undefined}>
                {run.text}
              </Text>
            ))}
          </Text>
          <Text style={tail.bold ? styles.bold : undefined}>{tail.text}</Text>
        </React.Fragment>
      );
    }
  }
  return renderRuns(line.runs);
}

export function AndroidJustifiedText({ runs, fontSize, lineHeight, color }: Props) {
  const { fontScale } = useWindowDimensions();
  const [containerWidth, setContainerWidth] = useState(0);
  const [state, setState] = useState<JustifyState>(() => ({
    key: '',
    result: 'measuring',
  }));

  const justifyRuns = useMemo<JustifyRun[]>(
    () => runs.map(([text, bold]) => ({ text, bold })),
    [runs],
  );
  const sourceText = useMemo(() => justifyRuns.map((run) => run.text).join(''), [justifyRuns]);
  const boldSignature = justifyRuns.map((run) => (run.bold ? '1' : '0')).join('');
  // 宽度、系统字号、文本或 bold 分布变化后必须重新测量；lineHeight 只影响垂直布局。
  const measureKey = `${containerWidth}|${fontScale}|${fontSize}|${sourceText}|${boldSignature}`;
  const result: Result = state.key === measureKey ? state.result : 'measuring';
  const finalLines = Array.isArray(result) ? result : null;
  const measurable = containerWidth > 0;
  const showFinal = measurable && finalLines !== null;
  const showMeasuring = measurable && result === 'measuring';

  useEffect(() => {
    setState({ key: measureKey, result: 'measuring' });
  }, [measureKey]);

  const handleLayout = useCallback((event: LayoutChangeEvent) => {
    const width = event.nativeEvent.layout.width;
    setContainerWidth((current) => (Math.abs(current - width) > 0.5 ? width : current));
  }, []);

  const handleFirstLayout = useCallback(
    (event: TextLayoutEvent) => {
      const measured = event.nativeEvent.lines;
      setState((current) => {
        if (current.key !== measureKey || current.result !== 'measuring') {
          return current;
        }
        if (measured.length <= 1) {
          return { ...current, result: 'native' };
        }
        const descriptors = buildLineDescriptors(justifyRuns, measured);
        if (!descriptors) {
          return { ...current, result: 'native' };
        }
        const nextLines = buildJustifiedLines(
          descriptors,
          measured.map((line) => line.width),
          containerWidth,
          fontScale,
        );
        if (!nextLines) {
          return { ...current, result: 'native' };
        }
        return { ...current, result: nextLines };
      });
    },
    [containerWidth, fontScale, justifyRuns, measureKey],
  );

  return (
    <View style={styles.container} onLayout={handleLayout} testID="agreement-justify-root">
      {showFinal && finalLines ? (
        <Text
          testID="agreement-justify-final"
          style={[
            styles.final,
            {
              width: containerWidth + FINAL_WIDTH_BUFFER,
              fontSize,
              lineHeight,
              color,
            },
          ]}
        >
          {finalLines.map((line, index) => (
            <React.Fragment key={index}>
              {renderJustifiedLine(line)}
              {index < finalLines.length - 1 ? '\n' : null}
            </React.Fragment>
          ))}
        </Text>
      ) : (
        <Text
          testID="agreement-justify-placeholder"
          style={{ fontSize, lineHeight, color, textAlign: 'justify' }}
        >
          {renderRuns(justifyRuns)}
        </Text>
      )}

      {showMeasuring ? (
        <View
          style={[styles.measureLayer, { width: containerWidth }]}
          pointerEvents="none"
          importantForAccessibility="no-hide-descendants"
        >
          <Text
            testID="agreement-justify-measure-first"
            style={[styles.measureText, { width: containerWidth, fontSize, lineHeight }]}
            onTextLayout={handleFirstLayout}
          >
            {renderRuns(justifyRuns)}
          </Text>
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { alignSelf: 'stretch' },
  final: { textAlign: 'left' },
  measureLayer: { position: 'absolute', left: 0, top: 0, opacity: 0 },
  measureText: { textAlign: 'left' },
  bold: { fontWeight: 'bold' },
});
