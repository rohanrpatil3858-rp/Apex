package com.example.demo.entity;

import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Column;
import jakarta.persistence.ManyToMany;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.NotEmpty;
import jakarta.validation.constraints.Email;
import java.util.List;


import com.fasterxml.jackson.annotation.JsonIgnore;

@Entity
public class Learner {

    @Id
    @GeneratedValue(strategy = GenerationType.AUTO)
    private Long learnerId;

    private String learnerName;

    @Column(unique = true)
    @NotNull
    @NotEmpty
    @Email
    private String learnerEmail;

    @ManyToMany(mappedBy = "learners")
    @JsonIgnore
    private List<Cohort> cohorts;

    public Learner() {
    }

    public Learner(String learnerName, String learnerEmail) {
        this.learnerName = learnerName;
        this.learnerEmail = learnerEmail;
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

    public List<Cohort> getCohorts() {
        return cohorts;
    }

    public void setCohorts(List<Cohort> cohorts) {
        this.cohorts = cohorts;
    }

}
