<!-- SPDX-FileCopyrightText: 2026 HanYang06 -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# 从零实现一个 iOS 风格的滚轮选择器（Wheel Picker）

> 物理引擎、3D 透视与跨平台设计语言的 Web 实现

---

## 一、引言

在移动端交互中，滚轮选择器（Wheel Picker）是最经典、最成熟的组件之一。从 iOS 的 `UIPickerView` 到 Android 的各类 WheelPicker 开源库，它的身影遍布系统闹钟、日期选择、省市区联动等场景。

这种组件看似简单——一个可滚动的选项列表加上选中高亮——但要在 Web 端做到真正的"iOS 质感"，远非加个 `overflow: scroll` 就能搞定。本文从一个真实项目的重构历程出发，剖析滚轮选择器的核心设计语言与技术实现，最终交付一个物理引擎驱动的、具备 3D 圆柱透视效果的完整方案。

---

## 二、设计语言：跨平台对比

### iOS: UIPickerView

Apple Human Interface Guidelines 将 Picker 定义为"一种用于从有序列表中选择单个值的紧凑型控件"。其核心交互特征：

- **物理滚轮隐喻**：选项排列在圆柱表面，上下滚动时有真实 wheel 的旋转感
- **3D 透视**：中间项最大最亮，向边缘逐渐缩小并淡出，模拟圆柱曲面的曲率
- **惯性动量**：手指滑动后继续以自然速度减速，摩擦系数恒定
- **精准吸附**：松手后自动对齐到最近的选项，不存在"卡在两个选项之间"的状态
- **实时选中**：滚动到哪个选项，哪个选项就立即高亮，无延迟

### Android: NumberPicker / WheelPicker

Android 原生 `NumberPicker` 长期受限于早期 Material Design 规范，视觉效果较为简陋。第三方社区（如 `WheelPicker`、`PickerView` 等库）实现了更接近 iOS 的效果：

- 同样基于物理惯性滚动模型
- 支持 3D 曲面变换（缩放 + 透明度衰减）
- 循环/非循环模式
- 联动选择

### 设计共性

| 特性 | iOS | Android | 我们的 Web 实现 |
|------|-----|---------|----------------|
| 物理惯性 | UIScrollView 原生 | Scroller / OverScroller | RAF 速度模型 |
| 3D 透视 | CATransform3D | Matrix + Canvas | CSS translateX + scale |
| 选中吸附 | UIPickerView 内建 | SnapHelper | 阈值检测 + 网格对齐 |
| 无限循环 | dataSource 虚拟化 | 数据复制 | DOM 3 拷贝 + 边界复位 |
| 实时选中 | scrollViewDidScroll | OnScrollListener | 每帧 emitCurrentValue |

---

## 三、核心技术挑战

### 3.1 物理引擎：速度模型与摩擦衰减

Web 原生滚动（`overflow: auto`）的惯性行为不可控：无法精确控制摩擦系数，无法在特定位置完美停靠，滚动条本身也破坏了视觉一致性。

**方案**：放弃原生 scroll，用 RAF（requestAnimationFrame）驱动一个连续速度模型。

核心状态只有两个变量：

```typescript
let offsetX = 0    // 轨道当前位置（像素）
let velocity = 0   // 当前速度（像素/帧）
```

每帧的更新逻辑：

```typescript
const step = () => {
  if (Math.abs(velocity) < THRESHOLD) {
    // 速度归零 → 吸附到最近网格位置
    snapToClosest()
    return
  }
  offsetX += velocity          // 位置增量
  velocity *= FRICTION          // 摩擦衰减
  applyOffset()                 // 更新 DOM
  checkBoundary()               // 无限循环边界
  updateTransforms()            // 3D 透视效果
  requestAnimationFrame(step)
}
```

这种模型天然支持所有交互方式的统一处理：

- **鼠标滚轮**：每 tick 施加固定 `velocity += impulse`
- **拖拽**：直接设置 `offsetX = dragStart + Δmouse`
- **拖拽释放**：记录末速度 `velocity = -dragVelocity × scale`，交给物理循环

### 3.2 3D 圆柱透视

真正的 3D 圆柱变换（如 iOS 原生）需要 `rotateX` + `translateZ` 组合，在 Web 上可以通过 CSS 3D transforms 实现。但为了保持简单的 DOM 结构和最佳性能，我们选择了 **2D 模拟 3D** 的方案：

每一项根据其距视口中心的距离，动态计算缩放和透明度：

```typescript
const dist = Math.abs(itemCenter - viewportCenter)
const t = Math.min(dist / maxDist, 1)
const scale = 1 - t * 0.28     // 最小 0.72
const opacity = 1 - t * 0.55   // 最小 0.45
```

再加上随距离增加的 `boxShadow`：

```typescript
if (t > 0.01) {
  const blur = 2 + t * 8
  item.style.boxShadow =
    `0 ${ceil(blur * 0.4)}px ${ceil(blur)}px rgba(0,0,0,${0.06 + t * 0.18})`
}
```

配合左右两侧的**渐变遮罩**，模拟圆柱曲面的光线衰减：

```css
.ar-wheel-picker__viewport::before {
  background: linear-gradient(to right, var(--bg-color), transparent);
}
.ar-wheel-picker__viewport::after {
  background: linear-gradient(to left, var(--bg-color), transparent);
}
```

### 3.3 无限循环：3 份拷贝 + 边界复位

真正的无限循环在 DOM 层面需要"假装"列表无限长。标准做法是将数据集复制 3 份渲染，通过视觉复位实现永无尽头的错觉。

```
[副本1: A0-A5] [副本2: A0-A5] [副本3: A0-A5]
                    ↑
              始终让用户看见这一份
```

当用户滚动到副本 3 的末端时，**瞬间将滚动位置调回副本 2 的对应位置**。由于三个副本渲染的内容完全一致，这个跳转在视觉上无缝衔接。

```typescript
const checkBoundary = () => {
  const vi = getVirtualIndex()
  const len = options.length
  if (vi < len) {
    // 进入副本1 → 跳回副本2
    offsetX -= len * ITEM_STEP
  } else if (vi >= len * 2) {
    // 进入副本3 → 跳回副本2
    offsetX += len * ITEM_STEP
  }
}
```

`getVirtualIndex()` 根据当前 `offsetX` 反算出正在居中的是第几个 DOM 元素（在 3 份拷贝中的绝对索引），再通过 `% len` 映射回原始数据集。

### 3.4 实时选中

滚动过程中，每帧都要判断当前居中的是哪个选项并发射 `update:modelValue`。关键在于**守卫冲突**：每次 emit 后，`v-model` 的 watch 回调会尝试修改 `offsetX`，与物理循环形成冲突。

**解决方案**：每次 emit 后设置一个单帧守卫（~16ms），下一帧自动释放。

```typescript
const markInternal = () => {
  internalChange = true
  requestAnimationFrame(() => {
    internalChange = false
  })
}
```

这确保了：
1. 物理循环能继续驱动 `offsetX`（watch 被守卫拦截）
2. 每隔 ~16ms 就能发射一次新值，没有可感知的延迟
3. 外部主动修改 `modelValue`（如父组件赋值）不受影响（守卫已释放）

---

## 四、实现方案演进

### 方案一：原生 scroll ❌

```css
overflow-x: auto;
```

**问题**：`deltaY` 值随设备差异巨大（鼠标 120px/tick vs 触控板 3px/tick），无法精确控制"滚一下跳一项"。同时 `scrollIntoView` + `scrollLeft` 的组合难以完美吸附，边界复位时出现视觉回弹。

### 方案二：CSS transform + 离散 animateTo ⚠️

```typescript
const animateTo = (target: number) => {
  // RAF 缓动动画：180ms → 100ms easeOutDecel
}
```

**问题**：`isAnimating` 守卫导致快速滚动时大量事件被丢弃，连续滚动体验断裂。可维护性差：`animateTo`、`applyMomentum`、`snapToClosest` 三套动画系统各自为政。

### 方案三：物理引擎 + RAF 连续驱动 ✅

```
onWheel → velocity += impulse
onDrag  → offsetX = dragStart + Δmouse
         → dragEnd → velocity = -dragVelocity × scale
                           ↓
             统一的物理循环（RAF）
                  ↓
         offsetX += velocity
         velocity *= friction
         checkBoundary()
         updateTransforms()
         emitCurrentValue()
```

**优势**：
- 所有交互路径（滚轮、拖拽、点击）统一到一个物理循环
- 永不丢弃事件：多个 wheel tick 自然累加速度
- 自然的减速和吸附：物理参数独立可调
- 代码结构清晰：~260 行完成所有功能

---

## 五、关键代码解析

### 物理常量调优

滚轮 1 tick 精确移动 1 项的数学关系：

```
总位移 = impulse / (1 - friction)

设定目标 = ITEM_STEP (42px), friction = 0.88
→ impulse = 42 × (1 - 0.88) = 5
```

```typescript
const FRICTION = 0.88
const WHEEL_IMPULSE = 5        // 1 tick = 1 项
const VELOCITY_THRESHOLD = 0.3 // 停止判定阈值
```

### 网格吸附

```typescript
const snapToClosest = () => {
  const vi = getVirtualIndex()
  offsetX = getOffsetForIndex(vi)  // 精确对齐到网格中心
  applyOffset()
  checkBoundary()
  updateTransforms()
  emitCurrentValue()
}
```

### 点击传索引

```html
@click="onItemClick(opt, i)"   <!-- i 是 v-for 的实际索引 -->
```

```typescript
const onItemClick = (value: string, vi: number) => {
  offsetX = getOffsetForIndex(vi)  // 精确跳到点击位置
  emit('update:modelValue', value)
}
```

这使得点击 A5 后面的 A0 时，跳到的是**副本 3 的 A0**（索引 12），而不是中间副本的 A0（索引 6），实现了自然的"往后继续"而不是"跳回"。

---

## 六、总结与思考

| 维度 | 结论 |
|------|------|
| **不要用原生 scroll 做 picker** | deltaY 不可控、无法完美吸附、边界处理困难 |
| **物理引擎是正确抽象** | 速度模型统一了滚轮/拖拽/点击三种交互 |
| **3 份拷贝是"穷人的无限循环"** | 简单有效，但大列表时需考虑 DOM 性能 |
| **CSS transform 优于 scroll** | 完全控制位置 + 不会触发浏览器 overscroll |
| **设计语言的本质是物理** | iOS 的"丝滑"来自对真实世界摩擦/惯性的精确建模 |

### 参考资料

- [Apple Human Interface Guidelines - Pickers](https://developer.apple.com/design/human-interface-guidelines/components/selection-and-input/pickers/)
- [Material Design - Pickers](https://m3.material.io/components/pickers)
- [Android WheelPicker (Open Source)](https://github.com/hexingbo/WheelPicker-master)
- [iOS PickerView 3D 透视原理 - CSDN](https://blog.csdn.net/zly921112/article/details/50401976)

---

*文中代码示例基于 Vue 3 + TypeScript，可直接改造使用。*
