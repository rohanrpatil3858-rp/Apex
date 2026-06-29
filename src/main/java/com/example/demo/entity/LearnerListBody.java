package com.example.demo.entity;

import java.util.List;

public class LearnerListBody {

    private List<Long> learnerIds;

    public LearnerListBody() {
    }

    public LearnerListBody(List<Long> learnerIds) {
        this.learnerIds = learnerIds;
    }

    public List<Long> getLearnerIds() {
        return learnerIds;
    }

    public void setLearnerIds(List<Long> learnerIds) {
        this.learnerIds = learnerIds;
    }
}
