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
 * - 系统字号或窗口宽度变化时由 RN 布局自动重排；
 * - Android 的 justify 段落统一由 AndroidJustifiedText 做字符级两端对齐（#313），
 *   包括纯英文/中英混合行；center 与其它平台保持原渲染路径。
 *
 * 与桌面 render_agreement_document 同契约：字段取值、默认值、\n 拆分、字号回退一致。
 */

import React from 'react';
import { Platform, ScrollView, StyleSheet, Text, TextStyle, View } from 'react-native';

import { AndroidJustifiedText } from './AndroidJustifiedText';
import {
  ALIGN_CENTER,
  ALIGN_JUSTIFY,
  AgreementBlock,
  AgreementPayload,
  AgreementRun,
  DEFAULT_BLOCK_FONT_SIZE,
  MAX_BLOCK_FONT_SIZE,
  MIN_BLOCK_FONT_SIZE,
} from '../utils/agreement';
import type { AppTheme } from '../utils/theme';

export {
  ALIGN_CENTER,
  ALIGN_JUSTIFY,
  DEFAULT_BLOCK_FONT_SIZE,
  MAX_BLOCK_FONT_SIZE,
  MIN_BLOCK_FONT_SIZE,
};
export type { AgreementBlock as Block, AgreementPayload, AgreementRun as Run };

export function blockFontSize(block: AgreementBlock): number {
  const value = block.font_size;
  if (typeof value !== 'number' || !Number.isInteger(value)) {
    return DEFAULT_BLOCK_FONT_SIZE;
  }
  if (value < MIN_BLOCK_FONT_SIZE || value > MAX_BLOCK_FONT_SIZE) {
    return DEFAULT_BLOCK_FONT_SIZE;
  }
  return value;
}

export function blockTextAlign(block: AgreementBlock): TextStyle['textAlign'] {
  return block.align === ALIGN_CENTER ? 'center' : 'justify';
}

export function blockLineHeight(block: AgreementBlock): number {
  return blockFontSize(block) * 1.5;
}

export function splitRunsOnNewline(runs: AgreementRun[]): [string, boolean][][] {
  const lines: [string, boolean][][] = [[]];
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
  block: AgreementBlock;
  textColor: string;
}

function BlockView({ block, textColor }: BlockViewProps) {
  const fontSize = blockFontSize(block);
  const lineHeight = blockLineHeight(block);
  const textAlign = blockTextAlign(block);
  const lines = splitRunsOnNewline(block.runs);
  // Android 的 justify 只能拉伸空格；Android 上所有 justify 行统一交给字符级
  // 对齐组件。纯英文/中英混合行也会加字间距，与 Android 15 的
  // JUSTIFICATION_MODE_INTER_CHARACTER 行为一致。
  const useAndroidJustify = Platform.OS === 'android' && textAlign === 'justify';

  return (
    <View style={styles.block}>
      {lines.map((line, lineIndex) => {
        if (useAndroidJustify && line.length > 0) {
          return (
            <AndroidJustifiedText
              key={lineIndex}
              runs={line}
              fontSize={fontSize}
              lineHeight={lineHeight}
              color={textColor}
            />
          );
        }
        return (
          <Text
            key={lineIndex}
            style={{ fontSize, lineHeight, textAlign, color: textColor }}
          >
            {line.map(([text, bold], runIndex) => (
              <Text key={runIndex} style={bold ? styles.bold : undefined}>
                {text}
              </Text>
            ))}
          </Text>
        );
      })}
    </View>
  );
}

interface RichAgreementProps {
  data: AgreementPayload | null;
  theme: AppTheme;
}

export function RichAgreement({ data, theme }: RichAgreementProps) {
  if (!data?.blocks?.length) {
    return null;
  }
  return (
    <ScrollView>
      {data.blocks.map((block, index) => (
        <BlockView key={index} block={block} textColor={theme.text} />
      ))}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  block: { marginBottom: 10 },
  bold: { fontWeight: 'bold' },
});