/**
 * 用户协议富文本渲染（UA-1 · issue #295）。
 *
 * 范围（对齐 #295 的验收标准与 spec「接口规范 1」）：
 * - 只渲染服务端 GET /auth/agreement 返回的 blocks/runs；
 * - 无签署、无倒计时、无同意或拒绝——只读视图。
 *
 * 渲染契约：
 * - 段落级 font_size（12–32，默认 16）映射到客户端逻辑字号；
 * - 段落级 align 仅 center（居中）/ justify（两端对齐），缺省 justify；
 * - runs 内 bold 局部加粗；连续普通空格与 \n 原样保留；
 * - 末行与显式换行前的行不拉伸：把 \n 拆成独立 <Text>，让每个显示行自成一个块，
 *   块的末行天然不参与两端对齐的拉伸；
 * - 不执行 HTML：HTML 会折叠连续空格，也会引入协议未允许的标记与交互；
 * - 系统字号或窗口宽度变化时由 RN 布局自动重排。
 *
 * 与桌面 render_agreement_document 同契约：字段取值、默认值、\n 拆分、字号回退一致。
 */

import React from 'react';
import { ScrollView, StyleSheet, Text, TextStyle, View } from 'react-native';

export const DEFAULT_BLOCK_FONT_SIZE = 16;
export const MIN_BLOCK_FONT_SIZE = 12;
export const MAX_BLOCK_FONT_SIZE = 32;

export const ALIGN_CENTER = 'center';
export const ALIGN_JUSTIFY = 'justify';

export const COLOR_TEXT = '#17283d';

export interface Run {
  text: string;
  bold?: boolean;
}

export interface Block {
  font_size?: number;
  align?: string;
  runs: Run[];
}

export interface AgreementPayload {
  version?: string;
  title?: string;
  format?: string;
  blocks?: Block[];
}

export function blockFontSize(block: Block): number {
  const value = block.font_size;
  if (typeof value !== 'number' || !Number.isInteger(value)) {
    return DEFAULT_BLOCK_FONT_SIZE;
  }
  if (value < MIN_BLOCK_FONT_SIZE || value > MAX_BLOCK_FONT_SIZE) {
    return DEFAULT_BLOCK_FONT_SIZE;
  }
  return value;
}

export function blockTextAlign(block: Block): TextStyle['textAlign'] {
  return block.align === ALIGN_CENTER ? 'center' : 'justify';
}

export function splitRunsOnNewline(runs: Run[]): Array<Array<[string, boolean]>> {
  const lines: Array<Array<[string, boolean]>> = [[]];
  for (const run of runs) {
    const text = typeof run.text === 'string' ? run.text : String(run.text);
    const bold = Boolean(run.bold);
    const parts = text.split('\n');
    parts.forEach((part, index) => {
      if (index > 0) {
        lines.push([]);
      }
      if (part) {
        lines[lines.length - 1].push([part, bold]);
      }
    });
  }
  return lines;
}

interface BlockViewProps {
  block: Block;
}

function BlockView({ block }: BlockViewProps) {
  const fontSize = blockFontSize(block);
  const textAlign = blockTextAlign(block);
  const lines = splitRunsOnNewline(block.runs);

  return (
    <View style={styles.block}>
      {lines.map((line, lineIndex) => (
        <Text
          key={lineIndex}
          style={[styles.line, { fontSize, textAlign, color: COLOR_TEXT }]}
        >
          {line.map(([text, bold], runIndex) => (
            <Text key={runIndex} style={bold ? styles.bold : undefined}>
              {text}
            </Text>
          ))}
        </Text>
      ))}
    </View>
  );
}

export function RichAgreement({ data }: { data: AgreementPayload | null }) {
  if (!data?.blocks?.length) {
    return null;
  }
  return (
    <ScrollView>
      {data.blocks.map((block, index) => (
        <BlockView key={index} block={block} />
      ))}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  block: { marginBottom: 10 },
  line: { lineHeight: 24 },
  bold: { fontWeight: 'bold' },
});