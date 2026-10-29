package com.recalldesk.application.search;

import com.recalldesk.domain.retrieval.FusionConfig;
import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.util.Map;
import org.junit.jupiter.api.Test;

/** 融合档位的取值与覆盖语义——权重合不合流是两种入口唯一的差别，最容易写错。 */
class FusionSpecTest {

    @Test
    void defaultsAreRrf60WithEqualGroupWeights() {
        FusionSpec spec = FusionSpec.defaults();
        assertThat(spec.method()).isEqualTo("rrf");
        assertThat(spec.rrfK()).isEqualTo(60);
        assertThat(spec.norm()).isEqualTo("minmax");
        assertThat(spec.weights()).containsOnlyKeys("dense", "sparse").containsValues(1.0);
        assertThat(spec.toConfig().weights()).containsExactly(
                Map.entry("dense", 1.0), Map.entry("sparse", 1.0)); // 出参 weights 保序
    }

    @Test
    void overlayReplacesGivenFieldsAndMergesWeightsByKey() {
        FusionSpec base = FusionSpec.defaults();

        assertThat(base.overlay(new FusionConfig("weighted", null, null, null)))
                .isEqualTo(new FusionSpec("weighted", 60, "minmax", Map.of("dense", 1.0, "sparse", 1.0)));
        // {sparse: 2} 是"sparse 加倍"，不是"只要 sparse"
        assertThat(base.overlay(new FusionConfig(null, null, null, Map.of("sparse", 2.0))))
                .isEqualTo(new FusionSpec("rrf", 60, "minmax", Map.of("dense", 1.0, "sparse", 2.0)));
        assertThat(base.overlay(null)).isEqualTo(base);
        // "没给"的判定：空串和 0 也算没给，不是非法输入
        assertThat(base.overlay(new FusionConfig("", 0, "", Map.of())))
                .isEqualTo(FusionSpec.defaults());
    }

    @Test
    void fromConfigDoesNotMergeWeightsIntoDefaults() {
        // 落库的配方是那次实验的事实：装配默认后来加了新组也不该重写历史
        assertThat(FusionSpec.fromConfig(new FusionConfig("weighted", 30, "zscore", Map.of("dense", 0.7))))
                .isEqualTo(new FusionSpec("weighted", 30, "zscore", Map.of("dense", 0.7)));
        assertThat(FusionSpec.fromConfig(null)).isEqualTo(FusionSpec.defaults());
        assertThat(FusionSpec.fromConfig(new FusionConfig(null, null, null, null)))
                .isEqualTo(FusionSpec.defaults());
        // 缺键回落到代码默认，但给了权重就整份照用
        assertThat(FusionSpec.fromConfig(new FusionConfig("weighted", null, null, Map.of("sparse", 3.0))))
                .isEqualTo(new FusionSpec("weighted", 60, "minmax", Map.of("sparse", 3.0)));
    }

    @Test
    void rejectsInvalidGear() {
        assertThatThrownBy(() -> new FusionSpec("bm25only", 60, "minmax", Map.of()))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("融合方法");
        assertThatThrownBy(() -> new FusionSpec("rrf", 60, "l2", Map.of()))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("归一化方式");
        assertThatThrownBy(() -> new FusionSpec("rrf", 0, "minmax", Map.of()))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("rrf_k");
        assertThatThrownBy(() -> new FusionSpec("rrf", 60, "minmax", Map.of("graph", 1.0)))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("权重只能按组给");
        assertThatThrownBy(() -> new FusionSpec("rrf", 60, "minmax", Map.of("dense", -1.0)))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("不能为负");
    }

    @Test
    void channelGroupPutsEveryDenseVariantInOneGroup() {
        assertThat(FusionSpec.channelGroup("dense_original")).isEqualTo("dense");
        assertThat(FusionSpec.channelGroup("dense_variant_2")).isEqualTo("dense");
        assertThat(FusionSpec.channelGroup("dense")).isEqualTo("dense");
        assertThat(FusionSpec.channelGroup("sparse")).isEqualTo("sparse");
        assertThatThrownBy(() -> FusionSpec.channelGroup("graph"))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessageContaining("未知通道 kind");
    }
}
