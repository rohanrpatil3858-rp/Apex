package com.example.demo.dto;

import java.util.List;

public class LearnerDTO {

    private Long learnerId;
    private String learnerName;
    private String learnerEmail;

    private List<CohortDTO> cohorts;

    public LearnerDTO() {
    }

    public LearnerDTO(Long learnerId, String learnerName, String learnerEmail, List<CohortDTO> cohorts) {
        this.learnerId = learnerId;
        this.learnerName = learnerName;
        this.learnerEmail = learnerEmail;
        this.cohorts = cohorts;
    }

    public Long getLearnerId() {
        return learnerId;
    }

    public void setLearnerId(Long learnerId) {
        this.learnerId = learnerId;
    }

    public String getLearnerName() {
        return learnerName;
    }

    public void setLearnerName(String learnerName) {
        this.learnerName = learnerName;
    }

    public String getLearnerEmail() {
        return learnerEmail;
    }

    public void setLearnerEmail(String learnerEmail) {
        this.learnerEmail = learnerEmail;
    }

    public List<CohortDTO> getCohorts() {
        return cohorts;
    }

    public void setCohorts(List<CohortDTO> cohorts) {
        this.cohorts = cohorts;
    }

}
