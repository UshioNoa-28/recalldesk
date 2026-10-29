package com.recalldesk;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.WebApplicationType;
import org.springframework.boot.autoconfigure.SpringBootApplication;

@SpringBootApplication
public class RecallDeskApplication {

    /**
     * 一个进程一类角色：设了 {@code recalldesk.worker.role} 的进程只跑后台循环，不起 web 容器。
     *
     * 一个 jar 换一个属性就换一个角色；角色到循环的映射在 {@code WorkerConfiguration}。
     * 这里必须在 run 之前定下来：WebApplicationType 是创建上下文之前就要定的东西，
     * 等懒解析 bean 来不及（那时 Tomcat 已经起来了）。
     */
    public static void main(String[] args) {
        SpringApplication application = new SpringApplication(RecallDeskApplication.class);
        if (workerRole(args) != null) {
            application.setWebApplicationType(WebApplicationType.NONE);
        }
        application.run(args);
    }

    /**
     * 从命令行 / 系统属性 / 环境变量里认角色，三种写法与 @ConditionalOnProperty 同键。
     *
     * 只做"要不要起 web 容器"这一个判断，所以刻意不解析成完整 Environment——
     * 属性绑定仍归 Spring，这里少一份自己的宽松绑定规则。
     */
    private static String workerRole(String[] args) {
        String prefix = "--recalldesk.worker.role=";
        for (String arg : args) {
            if (arg.startsWith(prefix)) {
                return orNull(arg.substring(prefix.length()));
            }
        }
        String fromProperty = orNull(System.getProperty("recalldesk.worker.role"));
        if (fromProperty != null) {
            return fromProperty;
        }
        return orNull(System.getenv("RECALLDESK_WORKER_ROLE"));
    }

    private static String orNull(String role) {
        return role == null || role.isBlank() ? null : role;
    }
}
