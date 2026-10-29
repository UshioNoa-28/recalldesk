package com.recalldesk.interfaces.config;

import com.recalldesk.application.document.DocumentService;
import com.recalldesk.application.eval.EvalRunService;
import com.recalldesk.application.search.SearchService;
import com.recalldesk.domain.port.model.TextSplitter;
import com.recalldesk.domain.port.ops.UnitOfWork;
import com.recalldesk.domain.port.persistence.ChunkIndex;
import com.recalldesk.domain.port.persistence.DocumentFileStorage;
import com.recalldesk.domain.port.persistence.DocumentRepository;
import com.recalldesk.domain.port.persistence.DocumentTaskRepository;
import com.recalldesk.domain.port.persistence.EvalRepository;
import com.recalldesk.domain.port.persistence.EvalRunRepository;
import com.recalldesk.domain.port.persistence.EvalRunTaskRepository;
import com.recalldesk.application.search.FusionSpec;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * 需要组合根读配置才能构造的用例服务。
 *
 * 就这两个：EvalRunService 的构造参数里有交互式检索的默认档（top-k 与融合默认档），
 * DocumentService 有每用户文档上限——这两个值是组合根从配置里读出来、
 * 切片后注入的，所以这里同样由组合根接线，而不是让应用层自己去读 env
 * （同一条纪律：settings 只读一次）。
 */
@Configuration(proxyBeanMethods = false)
public class ApplicationServiceConfiguration {

    @Bean
    public EvalRunService evalRunService(
            EvalRepository evals,
            EvalRunRepository runs,
            EvalRunTaskRepository runTasks,
            ChunkIndex chunkIndex,
            UnitOfWork unitOfWork,
            FusionSpec defaultFusion,
            @Value("${recalldesk.top-k}") int defaultTopK) {
        return new EvalRunService(evals, runs, runTasks, chunkIndex, unitOfWork, defaultTopK, defaultFusion);
    }

    @Bean
    public DocumentService documentService(
            DocumentRepository documents,
            DocumentFileStorage fileStorage,
            DocumentTaskRepository outbox,
            EvalRepository evals,
            EvalRunRepository evalRuns,
            ChunkIndex chunkIndex,
            TextSplitter textSplitter,
            SearchService searchService,
            UnitOfWork unitOfWork) {
        return new DocumentService(
                documents, fileStorage, outbox, evals, evalRuns, chunkIndex, textSplitter, searchService,
                unitOfWork);
    }
}
